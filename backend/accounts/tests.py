import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch

from django.db import IntegrityError, connections
from django.test import Client, LiveServerTestCase, TestCase, TransactionTestCase

from .models import User

VALID = {
    "name": "Ana García",
    "email": "ana@example.com",
    "password": "  contraseña íntegra 🙂  ",
    "role": "BUYER",
}


class RegistrationTests(TestCase):
    def post(self, data, **kwargs):
        return self.client.post("/api/auth/register", data=json.dumps(data), content_type="application/json", **kwargs)

    def assert_safe(self, response):
        text = response.content.decode()
        for secret in (VALID["password"], "pbkdf2_", "Traceback", "SELECT ", "INSERT ", "secret_database_credential"):
            self.assertNotIn(secret, text)
        if response.status_code == 201:
            self.assertNotIn('"password"', text)

    def test_valid_roles_and_exact_endpoint(self):
        for role in ("BUYER", "SELLER"):
            with self.subTest(role=role):
                response = self.post({**VALID, "role": role, "email": role.lower() + "@example.com"})
                self.assertEqual(response.status_code, 201)
                self.assertEqual(set(response.json()), {"id", "name", "email", "role"})
                self.assertEqual(response.json()["role"], role)
                self.assertNotIn("Location", response)
                self.assert_safe(response)
                self.assertEqual(response.cookies, {})
        self.assertEqual(User.objects.count(), 2)
        self.assertEqual(self.client.post("/api/auth/register/").status_code, 404)

    def test_required_fields_and_strict_types(self):
        for field in VALID:
            missing = dict(VALID)
            del missing[field]
            with self.subTest(field=field, value="absent"):
                self.assertEqual(self.post(missing).status_code, 400)
            for value in (None, 42, 3.14, True, False, [], {}, ["text"]):
                with self.subTest(field=field, value=value):
                    response = self.post({**VALID, field: value})
                    self.assertEqual(response.status_code, 400)
                    self.assertIn(field, response.json()["errors"])
                    self.assert_safe(response)
        self.assertEqual(User.objects.count(), 0)

    def test_invalid_form_rules(self):
        cases = {
            "name": ["", " ", " a ", "x" * 81],
            "email": ["", "not-an-email", "a b@example.com", "a@exa mple.com", "a\\tb@example.com",
                      "a" * 64 + "@" + "b" * 63 + "." + "c" * 63 + "." + "d" * 63 + ".com"],
            "password": ["", "x" * 14, "x" * 129],
            "role": ["", "seller", "buyer", "ADMIN", " SELLER", "BUYER "],
        }
        for field, values in cases.items():
            for value in values:
                with self.subTest(field=field, length=len(value)):
                    response = self.post({**VALID, field: value})
                    self.assertEqual(response.status_code, 400)
                    self.assertIn(field, response.json()["errors"])
                    self.assert_safe(response)
        self.assertEqual(User.objects.count(), 0)

    def test_boundary_lengths_and_unicode_password(self):
        for length, name in ((15, " ab "), (128, "ñ" * 80)):
            with self.subTest(length=length):
                password = " " + "🙂" * (length - 2) + " "
                response = self.post({**VALID, "name": name, "password": password, "email": f"a{length}@example.com"})
                self.assertEqual(response.status_code, 201)
                user = User.objects.get(pk=response.json()["id"])
                self.assertEqual(user.name, name.strip())
                self.assertTrue(user.check_password(password))
                self.assertFalse(user.check_password(password.strip()))

    def test_email_254_boundary(self):
        email = "a" * 64 + "@" + "b" * 63 + "." + "c" * 63 + "." + "d" * 57 + ".com"
        self.assertEqual(len(email), 254)
        self.assertEqual(self.post({**VALID, "email": email}).status_code, 201)

    def test_normalization_hash_and_duplicates(self):
        response = self.post({**VALID, "email": "  ANA@Example.COM  ", "name": "  Ana García  "})
        self.assertEqual(response.status_code, 201)
        user = User.objects.get()
        self.assertEqual(user.email, "ana@example.com")
        self.assertEqual(user.name, "Ana García")
        self.assertTrue(user.check_password(VALID["password"]))
        self.assertFalse(user.check_password(VALID["password"].strip()))
        self.assertNotEqual(user.password, VALID["password"])
        self.assertTrue(user.password.startswith("pbkdf2_sha256$"))
        for email in ("ana@example.com", "ANA@EXAMPLE.COM", "  Ana@Example.com  "):
            with self.subTest(email=email):
                duplicate = self.post({**VALID, "email": email})
                self.assertEqual(duplicate.status_code, 409)
                self.assert_safe(duplicate)
        self.assertEqual(User.objects.count(), 1)

    def test_malformed_json_and_body_types(self):
        for body in ("{", "null", "[]", "true", "42", '"text"'):
            with self.subTest(body=body):
                response = self.client.post("/api/auth/register", data=body, content_type="application/json")
                self.assertEqual(response.status_code, 400)
                self.assert_safe(response)
        self.assertEqual(self.client.post("/api/auth/register", VALID).status_code, 400)
        self.assertEqual(self.client.get("/api/auth/register").status_code, 405)
        self.assertEqual(User.objects.count(), 0)

    def test_failure_after_insert_rolls_back_and_logs_no_details(self):
        original_save = User.save

        def fail_after_save(user, *args, **kwargs):
            original_save(user, *args, **kwargs)
            raise RuntimeError("secret_database_credential " + VALID["password"])

        with patch.object(User, "save", fail_after_save), self.assertLogs("accounts.views", level="ERROR") as logs:
            response = self.post(VALID)
        self.assertEqual(response.status_code, 500)
        self.assert_safe(response)
        self.assertNotIn("secret_database_credential", " ".join(logs.output))
        self.assertNotIn(VALID["password"], " ".join(logs.output))
        self.assertEqual(User.objects.count(), 0)
        self.assertEqual(self.post(VALID).status_code, 201)

    def test_response_failure_rolls_back_insert(self):
        from .views import JsonResponse
        def fail_success(*args, **kwargs):
            if kwargs.get("status") == 201:
                raise RuntimeError("secret_database_credential")
            return JsonResponse(*args, **kwargs)

        with patch("accounts.views.JsonResponse", side_effect=fail_success), self.assertLogs("accounts.views", level="ERROR"):
            response = self.post(VALID)
        self.assertEqual(response.status_code, 500)
        self.assert_safe(response)
        self.assertEqual(User.objects.count(), 0)

    def test_other_integrity_error_is_not_reported_as_duplicate(self):
        with patch.object(User, "save", side_effect=IntegrityError("secret_database_credential")), self.assertLogs("accounts.views", level="ERROR"):
            response = self.post(VALID)
        self.assertEqual(response.status_code, 500)
        self.assert_safe(response)
        self.assertEqual(User.objects.count(), 0)

    def test_hash_failure_is_sanitized(self):
        with patch.object(User, "set_password", side_effect=RuntimeError(VALID["password"])), self.assertLogs("accounts.views", level="ERROR"):
            response = self.post(VALID)
        self.assertEqual(response.status_code, 500)
        self.assert_safe(response)
        self.assertEqual(User.objects.count(), 0)


    def test_password_composed_only_of_spaces_is_preserved(self):
        response = self.post({**VALID, "password": " " * 15})
        self.assertEqual(response.status_code, 201)
        self.assertTrue(User.objects.get().check_password(" " * 15))


class ConcurrentRegistrationTests(TransactionTestCase):
    def test_simultaneous_duplicates_use_database_uniqueness(self):
        barrier = Barrier(3)

        def register(email):
            connections.close_all()
            try:
                barrier.wait(timeout=10)
                response = Client().post(
                    "/api/auth/register",
                    data=json.dumps({**VALID, "email": email}),
                    content_type="application/json",
                )
                return response.status_code
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=3) as pool:
            statuses = list(pool.map(register, ["ana@example.com", " ANA@EXAMPLE.COM ", "Ana@Example.com"]))
        self.assertEqual(sorted(statuses), [201, 409, 409])
        self.assertEqual(User.objects.count(), 1)
        self.assertEqual(User.objects.get().email, "ana@example.com")


class PersistenceConstraintTests(TransactionTestCase):
    def test_database_rejects_duplicate_email_and_invalid_role(self):
        from django.db import transaction
        User.objects.create_user(**VALID)
        with self.assertRaises(IntegrityError), transaction.atomic():
            User.objects.create_user(**VALID)
        with self.assertRaises(IntegrityError), transaction.atomic():
            User.objects.create_user(**{**VALID, "email": "other@example.com", "role": "ADMIN"})
        self.assertEqual(User.objects.count(), 1)


class LocalHTTPTests(LiveServerTestCase):
    def test_real_local_http_register_and_conflict(self):
        from http.client import HTTPConnection
        from urllib.parse import urlsplit

        server = urlsplit(self.live_server_url)
        connection = HTTPConnection(server.hostname, server.port, timeout=10)
        try:
            payload = json.dumps(VALID).encode("utf-8")
            for expected in (201, 409):
                connection.request("POST", "/api/auth/register", body=payload,
                                   headers={"Content-Type": "application/json"})
                response = connection.getresponse()
                result = json.loads(response.read())
                self.assertEqual(response.status, expected)
                self.assertIsNone(response.getheader("Location"))
                self.assertIsNone(response.getheader("Set-Cookie"))
                self.assertNotIn("password", result)
                if expected == 201:
                    self.assertEqual(result["role"], "BUYER")
                    self.assertEqual(result["email"], VALID["email"])
            self.assertEqual(User.objects.count(), 1)
        finally:
            connection.close()
