import json
from unittest.mock import patch

from django.contrib.sessions.backends.db import SessionStore
from django.contrib.sessions.models import Session
from django.test import Client, TestCase

from .models import User


class LoginTests(TestCase):
    password = "  clave de login  "

    def setUp(self):
        self.user = User.objects.create_user(
            email="ana@example.com",
            password=self.password,
            name="Ana García",
            role="BUYER",
        )

    def post(self, data, **kwargs):
        return self.client.post("/api/auth/login", data=json.dumps(data), content_type="application/json", **kwargs)

    def assert_safe(self, response):
        body = response.content.decode()
        for secret in (self.password, self.user.password, "Traceback", "SELECT ", "INSERT "):
            self.assertNotIn(secret, body)

    def test_valid_credentials_normalize_email_and_create_session(self):
        response = self.post({"email": "  ANA@EXAMPLE.COM  ", "password": self.password}, secure=True)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"id": self.user.pk, "name": "Ana García", "email": "ana@example.com", "role": "BUYER"})
        self.assertIn("sessionid", response.cookies)
        cookie = response.cookies["sessionid"]
        self.assertTrue(cookie["httponly"])
        self.assertTrue(cookie["secure"])
        self.assertEqual(cookie["samesite"], "Lax")
        session = Session.objects.get(session_key=cookie.value).get_decoded()
        self.assertEqual(session["_auth_user_id"], str(self.user.pk))
        self.assert_safe(response)

    def test_one_character_password_is_checked_without_registration_minimum(self):
        user = User.objects.create_user(email="short@example.com", password="x", name="Short", role="SELLER")

        response = self.post({"email": user.email, "password": "x"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["role"], "SELLER")

    def test_invalid_email_and_password_have_same_unauthorized_message(self):
        wrong_password = self.post({"email": "ana@example.com", "password": "incorrecta"})
        unknown_email = self.post({"email": "nadie@example.com", "password": self.password})

        self.assertEqual(wrong_password.status_code, 401)
        self.assertEqual(unknown_email.status_code, 401)
        self.assertEqual(wrong_password.json(), {"error": "Email o contraseña incorrectos."})
        self.assertEqual(unknown_email.json(), wrong_password.json())
        self.assertEqual(Session.objects.count(), 0)
        self.assert_safe(wrong_password)
        self.assert_safe(unknown_email)

    def test_invalid_input_returns_field_errors(self):
        cases = [
            ({"email": "", "password": "x"}, "email"),
            ({"email": "not-an-email", "password": "x"}, "email"),
            ({"email": "ana@example.com", "password": ""}, "password"),
            ({"email": "ana@example.com", "password": "x" * 129}, "password"),
            ({"email": "ana@example.com"}, "password"),
        ]
        for data, field in cases:
            with self.subTest(data=data):
                response = self.post(data)
                self.assertEqual(response.status_code, 400)
                self.assertIn(field, response.json()["errors"])
                self.assertEqual(response.json()["errors"].get("email"), "Introduce un email válido." if field == "email" else None)
                self.assert_safe(response)
        self.assertEqual(Session.objects.count(), 0)

    def test_non_json_and_wrong_types_are_rejected(self):
        self.assertEqual(self.client.post("/api/auth/login", data="{}", content_type="text/plain").status_code, 400)
        for data in ({"email": 42, "password": "x"}, {"email": "ana@example.com", "password": 42}, None):
            response = self.post(data)
            self.assertEqual(response.status_code, 400)
            self.assertIn("errors", response.json())
            self.assertIn("body" if data is None else "email" if data["email"] == 42 else "password", response.json()["errors"])

    def test_login_failure_does_not_create_or_replace_session(self):
        response = self.post({"email": "ana@example.com", "password": "incorrecta"})

        self.assertEqual(response.status_code, 401)
        self.assertNotIn("sessionid", response.cookies)
        self.assertEqual(Session.objects.count(), 0)

    def test_session_failure_returns_500_and_leaves_no_session(self):
        with patch.object(SessionStore, "save", side_effect=RuntimeError("secret_database_credential")):
            with self.assertLogs("accounts.views", level="ERROR") as logs:
                response = self.post({"email": "ana@example.com", "password": self.password})

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json(), {"error": "No se pudo completar el inicio de sesión. Inténtalo de nuevo."})
        self.assertNotIn("sessionid", response.cookies)
        self.assertEqual(Session.objects.count(), 0)
        self.assertNotIn("secret_database_credential", response.content.decode())
        self.assertNotIn("secret_database_credential", " ".join(logs.output))
        self.assert_safe(response)

    def test_exact_route_and_method(self):
        self.assertEqual(self.client.get("/api/auth/login").status_code, 405)
        self.assertEqual(self.client.post("/api/auth/login/").status_code, 404)