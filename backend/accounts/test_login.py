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
        session_cookie = response.cookies.get("sessionid")
        secrets = [self.password, self.user.password, "Traceback", "SELECT ", "INSERT "]
        if session_cookie:
            secrets.append(session_cookie.value)
        for secret in secrets:
            self.assertNotIn(secret, body)

    def test_valid_credentials_normalize_email_and_create_session(self):
        response = self.post({"email": "  ANA@EXAMPLE.COM  ", "password": self.password}, secure=True)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"id": self.user.pk, "name": "Ana García", "email": "ana@example.com", "role": "BUYER"})
        self.assertIn("sessionid", response.cookies)
        cookie = response.cookies["sessionid"]
        self.assertTrue(cookie.value)
        self.assertEqual(cookie["path"], "/")
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
        self.assert_safe(response)

    def test_maximum_email_and_password_lengths_are_accepted(self):
        email = "a" * 64 + "@" + ".".join(["b" * 63, "c" * 63, "d" * 61])
        password = "x" * 128
        self.assertEqual(len(email), 254)
        user = User.objects.create_user(email=email, password=password, name="Maximum", role="BUYER")

        response = self.post({"email": email, "password": password}, secure=True)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["id"], user.pk)
        self.assertNotIn(password, response.content.decode())
        self.assertNotIn(user.password, response.content.decode())

    def test_invalid_email_and_password_have_same_unauthorized_message(self):
        wrong_password = self.post({"email": "ana@example.com", "password": "incorrecta"})
        trimmed_password = self.post({"email": "ana@example.com", "password": self.password.strip()})
        unknown_email = self.post({"email": "nadie@example.com", "password": self.password})

        self.assertEqual(wrong_password.status_code, 401)
        self.assertEqual(trimmed_password.status_code, 401)
        self.assertEqual(unknown_email.status_code, 401)
        self.assertEqual(wrong_password.json(), {"error": "Email o contraseña incorrectos."})
        self.assertEqual(trimmed_password.json(), wrong_password.json())
        self.assertEqual(unknown_email.json(), wrong_password.json())
        self.assertEqual(Session.objects.count(), 0)
        self.assert_safe(wrong_password)
        self.assert_safe(trimmed_password)
        self.assert_safe(unknown_email)

    def test_invalid_input_returns_field_errors(self):
        cases = [
            ({"email": "", "password": "x"}, "email"),
            ({"email": "not-an-email", "password": "x"}, "email"),
            ({"email": "a@" + ".".join(["b" * 63] * 3 + ["c" * 61]), "password": "x"}, "email"),
            ({"email": "ana@example.com", "password": ""}, "password"),
            ({"email": "ana@example.com", "password": "x" * 129}, "password"),
            ({"email": "ana@example.com"}, "password"),
            ({"password": "x"}, "email"),
            ({}, "email"),
        ]
        for data, field in cases:
            with self.subTest(data=data):
                response = self.post(data)
                self.assertEqual(response.status_code, 400)
                self.assertIn(field, response.json()["errors"])
                email_error = response.json()["errors"].get("email")
                if field == "email":
                    expected_email_error = (
                        "Campo obligatorio de tipo texto."
                        if "email" not in data or not isinstance(data["email"], str)
                        else "Introduce un email válido."
                    )
                    self.assertEqual(email_error, expected_email_error)
                else:
                    self.assertIsNone(email_error)
                self.assert_safe(response)
        self.assertEqual(Session.objects.count(), 0)

    def test_non_json_and_wrong_types_are_rejected(self):
        non_json = self.client.post("/api/auth/login", data="{}", content_type="text/plain")
        self.assertEqual(non_json.status_code, 400)
        self.assert_safe(non_json)
        for data in (
            {"email": 42, "password": "x"},
            {"email": "ana@example.com", "password": 42},
            {"email": None, "password": "x"},
            {"email": "ana@example.com", "password": None},
            None,
        ):
            response = self.post(data)
            self.assertEqual(response.status_code, 400)
            self.assertIn("errors", response.json())
            expected_field = "body" if data is None else "email" if not isinstance(data.get("email"), str) else "password"
            self.assertIn(expected_field, response.json()["errors"])
            self.assert_safe(response)
        self.assertEqual(Session.objects.count(), 0)

    def test_sessions_identify_only_the_account_that_authenticated(self):
        seller = User.objects.create_user(
            email="bea@example.com",
            password=self.password,
            name="Bea Vendedora",
            role="SELLER",
        )
        buyer_client = Client()
        seller_client = Client()

        buyer_login = buyer_client.post(
            "/api/auth/login",
            data=json.dumps({"email": " ANA@EXAMPLE.COM ", "password": self.password}),
            content_type="application/json",
            secure=True,
        )
        seller_login = seller_client.post(
            "/api/auth/login",
            data=json.dumps({"email": seller.email, "password": self.password}),
            content_type="application/json",
            secure=True,
        )

        self.assertEqual(buyer_login.status_code, 200)
        self.assertEqual(seller_login.status_code, 200)
        buyer_session = buyer_login.cookies["sessionid"].value
        seller_session = seller_login.cookies["sessionid"].value
        self.assertNotEqual(buyer_session, seller_session)
        self.assertEqual(Session.objects.count(), 2)

        buyer_identity = buyer_client.get("/api/auth/me", secure=True)
        seller_identity = seller_client.get("/api/auth/me", secure=True)
        self.assertEqual(buyer_identity.json(), {"id": self.user.pk, "name": "Ana García", "email": self.user.email, "role": "BUYER"})
        self.assertEqual(seller_identity.json(), {"id": seller.pk, "name": seller.name, "email": seller.email, "role": "SELLER"})
        self.assert_safe(buyer_login)
        self.assert_safe(seller_login)
        self.assertNotIn(buyer_session, buyer_identity.content.decode())
        self.assertNotIn(seller_session, seller_identity.content.decode())

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

    def test_credential_verification_failure_returns_generic_error_without_session(self):
        with patch.object(User, "check_password", side_effect=RuntimeError("secret_credential_failure")):
            with self.assertLogs("accounts.views", level="ERROR") as logs:
                response = self.post({"email": "ana@example.com", "password": self.password})

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json(), {"error": "No se pudo completar el inicio de sesión. Inténtalo de nuevo."})
        self.assertNotIn("sessionid", response.cookies)
        self.assertEqual(Session.objects.count(), 0)
        self.assertNotIn("secret_credential_failure", response.content.decode())
        self.assertNotIn("secret_credential_failure", " ".join(logs.output))
        self.assert_safe(response)

    def test_exact_route_and_method(self):
        self.assertEqual(self.client.get("/api/auth/login").status_code, 405)
        self.assertEqual(self.client.post("/api/auth/login/").status_code, 404)