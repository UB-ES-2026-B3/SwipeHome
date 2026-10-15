import json
from datetime import timedelta
from unittest.mock import patch

from django.contrib.sessions.models import Session
from django.db import DatabaseError
from django.test import Client, TestCase
from django.utils import timezone

from .models import User
from .tests import VALID


class CurrentUserTests(TestCase):
    def register(self, client, **values):
        response = client.post("/api/auth/register", data=json.dumps({**VALID, **values}), content_type="application/json", secure=True)
        self.assertEqual(response.status_code, 201)
        return response

    def test_both_roles_and_repeated_requests_with_only_session_cookie(self):
        for role in ("SELLER", "BUYER"):
            with self.subTest(role=role):
                client = Client()
                registration = self.register(client, role=role, email=role.lower() + "@example.com")
                subsequent = Client(enforce_csrf_checks=True)
                subsequent.cookies["sessionid"] = registration.cookies["sessionid"].value
                for _ in range(3):
                    response = subsequent.get("/api/auth/me?id=999&role=ADMIN", secure=True)
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.json(), registration.json())
                    self.assertIn("no-store", response["Cache-Control"])
                    self.assertIn("Cookie", response["Vary"])
                    self.assertNotIn(registration.cookies["sessionid"].value, response.content.decode())
                    self.assertNotIn("sessionid", response.cookies)
                    self.assertNotIn("password", response.json())
                    self.assertNotIn("pbkdf2_", response.content.decode())

    def test_anonymous_and_invalid_session_are_401_without_redirect(self):
        for cookie in (None, "invalid-session-value"):
            client = Client()
            if cookie:
                client.cookies["sessionid"] = cookie
            response = client.get("/api/auth/me", secure=True)
            self.assertEqual(response.status_code, 401)
            self.assertEqual(response.json(), {"error": "No hay una sesion autenticada."})
            self.assertIn("no-store", response["Cache-Control"])
            self.assertNotIn("Location", response)
            self.assertEqual(Session.objects.count(), 0)

    def test_expired_session_is_401(self):
        response = self.register(self.client)
        Session.objects.filter(session_key=response.cookies["sessionid"].value).update(expire_date=timezone.now() - timedelta(seconds=1))
        self.assertEqual(self.client.get("/api/auth/me", secure=True).status_code, 401)

    def test_deleted_account_is_401(self):
        response = self.register(self.client)
        User.objects.get(pk=response.json()["id"]).delete()
        self.assertEqual(self.client.get("/api/auth/me", secure=True).status_code, 401)

    def test_changed_password_invalidates_session(self):
        response = self.register(self.client)
        user = User.objects.get(pk=response.json()["id"])
        user.set_password("otra contrasena completa")
        user.save(update_fields=["password"])
        self.assertEqual(self.client.get("/api/auth/me", secure=True).status_code, 401)

    def test_profile_and_role_are_loaded_from_database(self):
        response = self.register(self.client)
        User.objects.filter(pk=response.json()["id"]).update(name="Nuevo nombre", role="SELLER", email="nuevo@example.com")
        current = self.client.get("/api/auth/me", secure=True)
        self.assertEqual(current.json(), {"id": response.json()["id"], "name": "Nuevo nombre", "email": "nuevo@example.com", "role": "SELLER"})

    def test_only_get_and_exact_path(self):
        self.assertEqual(self.client.post("/api/auth/me").status_code, 405)
        self.assertEqual(self.client.get("/api/auth/me/").status_code, 404)

    def test_identity_lookup_error_is_generic_and_logs_no_details(self):
        self.register(self.client)
        with patch("django.contrib.auth.backends.ModelBackend.get_user", side_effect=DatabaseError("secret_database_credential")), self.assertLogs("accounts.views", level="ERROR") as logs:
            response = self.client.get("/api/auth/me", secure=True)
        self.assertEqual(response.status_code, 500)
        self.assertIn("no-store", response["Cache-Control"])
        self.assertNotIn("secret_database_credential", response.content.decode())
        self.assertNotIn("secret_database_credential", " ".join(logs.output))
        self.assertNotIn("Traceback", response.content.decode())
