import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch

from django.db import IntegrityError, connections
from django.test import Client, TestCase, TransactionTestCase, override_settings

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
                self.assertIn("sessionid", response.cookies)
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
        self.assertEqual(self.client.get("/api/auth/register").status_code, 200)
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




# Identity endpoint exists only in the test URL configuration.
from django.http import JsonResponse
from django.urls import path
from django.contrib.sessions.models import Session
from django.contrib.sessions.backends.db import SessionStore
from .views import register


def identity(request):
    if not request.user.is_authenticated:
        return JsonResponse({"error": "Unauthenticated"}, status=401)
    return JsonResponse({"id": request.user.pk, "role": request.user.role})


urlpatterns = [path("api/auth/register", register), path("test/identity", identity)]


@override_settings(ROOT_URLCONF="accounts.tests")
class SessionRegistrationTests(TestCase):
    post = RegistrationTests.post
    assert_safe = RegistrationTests.assert_safe
    def test_sessions_for_roles_and_repeated_requests(self):
        for role in ("SELLER", "BUYER"):
            self.client = Client()
            response = self.post({**VALID, "email": role.lower() + "@example.com", "role": role}, secure=True)
            cookie = response.cookies["sessionid"]
            self.assertTrue(cookie["httponly"])
            self.assertTrue(cookie["secure"])
            self.assertEqual(cookie["samesite"], "Lax")
            self.assertNotIn(cookie.value, response.content.decode())
            stored = Session.objects.get(session_key=cookie.value).get_decoded()
            self.assertEqual(stored["_auth_user_id"], str(response.json()["id"]))
            # Fresh client represents a later page request, with just its cookie.
            subsequent = Client()
            subsequent.cookies["sessionid"] = cookie.value
            for _ in range(3):
                result = subsequent.get("/test/identity?id=999&role=ADMIN", secure=True)
                self.assertEqual(result.json(), {"id": response.json()["id"], "role": role})
            user = User.objects.get(pk=response.json()["id"])
            user.role = "BUYER" if role == "SELLER" else "SELLER"
            user.save()
            self.assertEqual(subsequent.get("/test/identity", secure=True).json()["role"], user.role)
        self.assertEqual(Client().get("/test/identity", secure=True).status_code, 401)

    def test_rotation_invalidates_old_session(self):
        old = self.client.session
        old["anonymous"] = True
        old.save()
        old_key = old.session_key
        response = self.post(VALID)
        self.assertNotEqual(response.cookies["sessionid"].value, old_key)
        self.assertFalse(Session.objects.filter(session_key=old_key).exists())

    def test_rejected_registration_does_not_create_session(self):
        self.assertEqual(self.post({**VALID, "role": "ADMIN"}).status_code, 400)
        self.assertEqual(Session.objects.count(), 0)
        User.objects.create_user(**VALID)
        response = self.post(VALID)
        self.assertEqual(response.status_code, 409)
        self.assertNotIn("sessionid", response.cookies)
        self.assertEqual(Session.objects.count(), 0)

    def test_session_failure_after_save_rolls_back_account_and_session(self):
        save = SessionStore.save
        def fail(store, *args, **kwargs):
            save(store, *args, **kwargs)
            if "_auth_user_id" in store:
                raise RuntimeError("secret_database_credential")
        with patch.object(SessionStore, "save", fail), self.assertLogs("accounts.views", level="ERROR"):
            response = self.post(VALID)
        self.assertEqual(response.status_code, 500)
        self.assert_safe(response)
        self.assertNotIn("sessionid", response.cookies)
        self.assertEqual(User.objects.count(), 0)
        self.assertEqual(Session.objects.count(), 0)
        self.assertEqual(self.client.get("/test/identity").status_code, 401)

    def test_failed_registration_preserves_existing_authentication(self):
        first = self.post(VALID)
        key = first.cookies["sessionid"].value
        with patch.object(SessionStore, "save", side_effect=RuntimeError("secret")), self.assertLogs("accounts.views", level="ERROR"):
            response = self.post({**VALID, "email": "other@example.com"})
        self.assertEqual(response.status_code, 500)
        self.assertNotIn("sessionid", response.cookies)
        self.assertEqual(User.objects.count(), 1)
        self.assertTrue(Session.objects.filter(session_key=key).exists())
        self.assertEqual(self.client.get("/test/identity").json()["id"], first.json()["id"])

    def test_csrf_is_enforced_with_https_and_origin(self):
        client = Client(enforce_csrf_checks=True)
        def post(**headers):
            return client.post("/api/auth/register", data=json.dumps(VALID), content_type="application/json", secure=True, **headers)
        self.assertEqual(post().status_code, 403)
        bootstrap = client.get("/api/auth/register", secure=True)
        token = bootstrap.json()["csrfToken"]
        self.assertTrue(bootstrap.cookies["csrftoken"]["secure"])
        self.assertEqual(post(HTTP_X_CSRFTOKEN=token, HTTP_ORIGIN="https://evil.example").status_code, 403)
        self.assertEqual(User.objects.count(), 0)
        self.assertEqual(Session.objects.count(), 0)
        response = post(HTTP_X_CSRFTOKEN=token, HTTP_ORIGIN="https://testserver")
        self.assertEqual(response.status_code, 201)
        self.assertNotEqual(client.cookies["csrftoken"].value, bootstrap.cookies["csrftoken"].value)


@override_settings(ROOT_URLCONF="accounts.tests")
class LocalHTTPSTests(TransactionTestCase):
    def test_real_local_https_cookie_and_authenticated_requests(self):
        import os
        import ssl
        from http.cookiejar import CookieJar
        from threading import Thread
        from urllib.request import build_opener, HTTPCookieProcessor, HTTPSHandler, Request
        from urllib.error import HTTPError
        from accounts.management.commands.runhttps import https_server
        cert, key = os.environ.get("LOCAL_TLS_CERT"), os.environ.get("LOCAL_TLS_KEY")
        if not cert or not key:
            self.skipTest("Set LOCAL_TLS_CERT and LOCAL_TLS_KEY to run real HTTPS verification")
        server = https_server(cert, key, port=0)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"https://localhost:{server.server_port}"
        jar = CookieJar()
        opener = build_opener(HTTPCookieProcessor(jar), HTTPSHandler(context=ssl.create_default_context(cafile=cert)))
        try:
            with opener.open(base + "/api/auth/register", timeout=10) as response:
                token = json.load(response)["csrfToken"]
            request = Request(base + "/api/auth/register", data=json.dumps(VALID).encode(), headers={"Content-Type": "application/json", "X-CSRFToken": token, "Origin": base})
            with opener.open(request, timeout=10) as response:
                self.assertEqual(response.status, 201)
                user = json.load(response)
                headers = response.headers.get_all("Set-Cookie")
                session_header = next(h for h in headers if h.startswith("sessionid="))
                for attribute in ("HttpOnly", "Secure", "SameSite=Lax"):
                    self.assertIn(attribute, session_header)
            session_cookie = next(c for c in jar if c.name == "sessionid")
            self.assertTrue(session_cookie.secure)
            for _ in range(3):
                with opener.open(base + "/test/identity", timeout=10) as response:
                    self.assertEqual(json.load(response), {"id": user["id"], "role": "BUYER"})
            # Duplicate request needs the rotated CSRF token.
            token = next(c.value for c in jar if c.name == "csrftoken")
            request = Request(base + "/api/auth/register", data=json.dumps(VALID).encode(), headers={"Content-Type": "application/json", "X-CSRFToken": token, "Origin": base})
            with self.assertRaises(HTTPError) as error:
                opener.open(request, timeout=10)
            self.assertEqual(error.exception.code, 409)
            self.assertFalse(any(h.startswith("sessionid=") for h in (error.exception.headers.get_all("Set-Cookie") or [])))
            error.exception.close()
            self.assertEqual(User.objects.count(), 1)
            self.assertEqual(Session.objects.count(), 1)
        finally:
            server.shutdown()
            thread.join(timeout=10)
            server.server_close()


class RegistrationCommitTests(TransactionTestCase):
    def test_commit_failure_rolls_back_account_and_session(self):
        from django.db import connection, DatabaseError
        with patch.object(connection, "commit", side_effect=DatabaseError("secret_database_credential")), self.assertLogs("accounts.views", level="ERROR"):
            response = self.client.post("/api/auth/register", data=json.dumps(VALID), content_type="application/json")
        self.assertEqual(response.status_code, 500)
        self.assertNotIn("sessionid", response.cookies)
        self.assertEqual(User.objects.count(), 0)
        self.assertEqual(Session.objects.count(), 0)
