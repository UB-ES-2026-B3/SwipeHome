import json
import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace
from unittest import skipUnless
from unittest.mock import Mock, patch

from django.test import Client, SimpleTestCase
from firebase_admin import auth, delete_app, initialize_app
from google.auth.credentials import AnonymousCredentials
from google.api_core.exceptions import ServiceUnavailable
from google.cloud import firestore

from . import repository
from .passwords import IncorrectPassword, change_password
from .test_views import FirebaseMocks, UID

PROFILE = {"uid": UID, "name": "Ana", "email": "ana@example.com", "role": "BUYER"}


class ProfileTests(FirebaseMocks, SimpleTestCase):
    def setUp(self):
        super().setUp()
        self.get_profile.return_value = dict(PROFILE)
        self.update = self.start(patch("accounts.profile_views.repository.update_user_profile", return_value=dict(PROFILE)))
        self.start(patch("accounts.profile_views.auth.create_custom_token", return_value=b"continuity"))
        self.start(patch("accounts.profile_views.get_app"))

    def send(self, data, method="patch", path="/api/auth/me"):
        return getattr(self.client, method)(
            path, data=json.dumps(data), content_type="application/json",
            HTTP_AUTHORIZATION="Bearer token",
        )

    def test_partial_update_both_methods_and_roles(self):
        for method in ("patch", "put"):
            for role in ("BUYER", "SELLER"):
                self.update.return_value = {**PROFILE, "role": role, "name": "Nuevo"}
                response = self.send({"name": " Nuevo "}, method)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json(), self.update.return_value)
                self.update.assert_called_with(UID, {"name": "Nuevo"})
                self.assertIn("no-store", response["Cache-Control"])

    def test_identity_role_unknown_fields_empty_and_types(self):
        for field in ("id", "uid", "role", "seller_uid", "password", "extra"):
            self.assertEqual(self.send({"name": "Nuevo", field: "other"}).status_code, 400)
        for data in ({}, [], None, {"name": None}, {"email": 42}, {"name": "x"},
                     {"name": "x" * 81}, {"email": "a b@example.com"}):
            with self.subTest(data=data):
                self.assertEqual(self.send(data).status_code, 400)
        self.update.assert_not_called()

    def test_invalid_json_and_content_type(self):
        for body, content_type in (("{", "application/json"), ("{}", "text/plain")):
            response = self.client.patch("/api/auth/me", body, content_type=content_type,
                                         HTTP_AUTHORIZATION="Bearer token")
            self.assertEqual(response.status_code, 400)

    def test_normalization_and_continuity_on_email_change(self):
        response = self.send({"email": " ANA@Example.COM "})
        self.assertEqual(response.status_code, 200)
        self.update.assert_called_once_with(UID, {"email": "ana@example.com"})
        self.assertEqual(response.json()["custom_token"], "continuity")

    def test_duplicate_maps_to_conflict(self):
        self.update.side_effect = auth.EmailAlreadyExistsError("secret_backend_detail", None, None)
        response = self.send({"name": "Nuevo", "email": "other@example.com"})
        self.assertEqual(response.status_code, 409)
        self.assert_safe(response)

    def test_server_failure_generic_and_no_secret_logs(self):
        self.update.side_effect = ServiceUnavailable("secret_backend_detail")
        with self.assertLogs("accounts.profile_views", level="ERROR") as logs:
            response = self.send({"name": "Nuevo"})
        self.assertEqual(response.status_code, 500)
        self.assert_safe(response, logs.output)

    def test_requires_authentication(self):
        self.assertEqual(self.client.patch("/api/auth/me", "{}", content_type="application/json").status_code, 401)
        self.update.assert_not_called()

    def test_password_validation_current_check_and_continuity(self):
        with patch("accounts.profile_views.change_password", return_value="continuity") as change:
            for data in ({}, {"current_password": "x", "new_password": "short"},
                         {"current_password": 1, "new_password": "x" * 15},
                         {"current_password": "x", "new_password": " " * 15},
                         {"current_password": "x" * 15, "new_password": "x" * 15},
                         {"current_password": "x", "new_password": "x" * 15, "uid": "other"}):
                self.assertEqual(self.send(data, "post", "/api/auth/me/password").status_code, 400)
            change.assert_not_called()
            data = {"current_password": "old", "new_password": " New password 1! "}
            change.side_effect = IncorrectPassword()
            self.assertEqual(self.send(data, "post", "/api/auth/me/password").status_code, 400)
            change.side_effect = None
            response = self.send(data, "post", "/api/auth/me/password")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), {"custom_token": "continuity"})
            change.assert_called_with(UID, "old", " New password 1! ")
            self.verify.return_value = {"uid": UID, "auth_time": 200}
            self.assertEqual(self.client.get("/api/auth/me", HTTP_AUTHORIZATION="Bearer replacement").status_code, 200)

    def test_password_failure_has_no_hash_or_password(self):
        with patch("accounts.profile_views.change_password", side_effect=RuntimeError("secret_backend_detail")):
            with self.assertLogs("accounts.profile_views", level="ERROR"):
                response = self.send({"current_password": "old", "new_password": "New password value 1!"}, "post", "/api/auth/me/password")
        self.assertEqual(response.status_code, 500)
        self.assert_safe(response)
        self.assertNotIn("new password value", response.content.decode())


class LogoutTests(FirebaseMocks, SimpleTestCase):
    def setUp(self):
        super().setUp()
        self.revoked = set()
        self.revoked_lookup.side_effect = lambda uid, timestamp: (uid, timestamp) in self.revoked
        self.revoke = self.start(patch("accounts.repository.revoke_session",
                                      side_effect=lambda uid, timestamp: self.revoked.add((uid, timestamp))))
        self.get_profile.return_value = dict(PROFILE)

    def test_idempotence_and_replay_even_after_refresh(self):
        for _ in range(2):
            response = self.client.post("/api/auth/logout", HTTP_AUTHORIZATION="Bearer token")
            self.assertEqual(response.status_code, 204)
            self.assertEqual(response.content, b"")
            self.assert_safe(response)
        self.assertEqual(self.client.get("/api/auth/me", HTTP_AUTHORIZATION="Bearer refreshed-token").status_code, 401)
        self.assertEqual(self.client.post("/api/inmuebles", HTTP_AUTHORIZATION="Bearer refreshed-token").status_code, 401)
        self.delete_user.assert_not_called()
        self.create_profile.assert_not_called()

    def test_missing_expired_and_get(self):
        self.assertEqual(self.client.post("/api/auth/logout").status_code, 204)
        self.assertEqual(self.client.get("/api/auth/logout").status_code, 405)
        self.verify.side_effect = auth.ExpiredIdTokenError("expired", None)
        self.assertEqual(self.client.post("/api/auth/logout", HTTP_AUTHORIZATION="Bearer expired").status_code, 204)

    def test_other_sessions_and_users_remain_valid(self):
        self.client.post("/api/auth/logout", HTTP_AUTHORIZATION="Bearer first")
        for uid, timestamp in ((UID, 101), ("other-user", 100)):
            self.verify.return_value = {"uid": uid, "auth_time": timestamp}
            self.assertEqual(self.client.get("/api/auth/me", HTTP_AUTHORIZATION="Bearer other").status_code, 200)

    def test_storage_failure_is_500_not_success(self):
        self.revoke.side_effect = ServiceUnavailable("secret_backend_detail")
        with self.assertLogs("accounts.profile_views", level="ERROR") as logs:
            response = self.client.post("/api/auth/logout", HTTP_AUTHORIZATION="Bearer token")
        self.assertEqual(response.status_code, 500)
        self.assert_safe(response, logs.output)

    def test_cookie_only_does_not_revoke(self):
        client = Client(enforce_csrf_checks=True)
        client.cookies["sessionid"] = "not-used"
        self.assertEqual(client.post("/api/auth/logout").status_code, 204)
        self.revoke.assert_not_called()


class RepositoryProfileTests(SimpleTestCase):
    def setUp(self):
        self.profile = self.enterContext(patch("accounts.repository.get_user_profile", return_value=dict(PROFILE)))
        self.app = self.enterContext(patch("accounts.repository.get_app"))
        self.update = self.enterContext(patch("accounts.repository.auth.update_user"))
        self.update.return_value = SimpleNamespace(display_name="Nuevo", email="ana@example.com")

    def test_one_write_for_name_email(self):
        result = repository.update_user_profile(UID, {"name": "Nuevo", "email": " ANA@example.com "})
        self.update.assert_called_once_with(UID, app=self.app.return_value, display_name="Nuevo", email="ana@example.com")
        self.assertEqual(result, {**PROFILE, "name": "Nuevo"})

    def test_email_change_clears_verification_and_preserves_omitted_name(self):
        repository.update_user_profile(UID, {"email": "new@example.com"})
        self.update.assert_called_once_with(UID, app=self.app.return_value,
                                            email="new@example.com", email_verified=False)

    def test_rejected_write_does_not_attempt_compensating_overwrite(self):
        self.update.side_effect = auth.EmailAlreadyExistsError("duplicate", None, None)
        with self.assertRaises(auth.EmailAlreadyExistsError):
            repository.update_user_profile(UID, {"name": "Nuevo", "email": "taken@example.com"})
        self.assertEqual(self.update.call_count, 1)
        self.assertEqual(self.profile.return_value, PROFILE)

    def test_revocation_document_is_persistent_and_contains_no_token(self):
        with patch("accounts.repository.firestore.client") as client:
            repository.revoke_session(UID, 100)
            document = client.return_value.collection.return_value.document
            self.assertEqual(len(document.call_args.args[0]), 64)
            document.return_value.set.assert_called_once_with({"revoked": True})


class PasswordServiceTests(SimpleTestCase):
    def setUp(self):
        self.enterContext(patch.dict(os.environ, {"FIREBASE_WEB_API_KEY": "test-key"}))
        self.enterContext(patch("accounts.passwords.get_app"))
        self.enterContext(patch("accounts.passwords.auth.get_user", return_value=SimpleNamespace(email="ana@example.com")))
        self.update = self.enterContext(patch("accounts.passwords.auth.update_user"))
        self.custom = self.enterContext(patch("accounts.passwords.auth.create_custom_token", return_value=b"continuity"))
        self.post = self.enterContext(patch("accounts.passwords.requests.post"))
        self.post.return_value = Mock(status_code=200)
        self.post.return_value.json.return_value = {"localId": UID, "passwordHash": "never-expose"}

    def test_reauth_before_single_password_write_and_continuity(self):
        self.assertEqual(change_password(UID, " old ", " new password 🙂 "), "continuity")
        self.assertEqual(self.post.call_args.kwargs["json"]["password"], " old ")
        self.assertEqual(self.post.call_args.kwargs["timeout"], (5, 15))
        self.assertEqual(self.update.call_args.kwargs["password"], " new password 🙂 ")
        self.assertEqual(self.update.call_args.args, (UID,))

    def test_wrong_password_or_uid_never_changes_password(self):
        self.post.return_value.status_code = 400
        self.post.return_value.json.return_value = {"error": {"message": "INVALID_LOGIN_CREDENTIALS"}}
        with self.assertRaises(IncorrectPassword):
            change_password(UID, "wrong", "new password value")
        self.post.return_value.status_code = 200
        self.post.return_value.json.return_value = {"localId": "other"}
        with self.assertRaises(IncorrectPassword):
            change_password(UID, "old", "new password value")
        self.update.assert_not_called()

    def test_network_or_signing_failure_before_write(self):
        self.post.side_effect = TimeoutError()
        with self.assertRaises(TimeoutError):
            change_password(UID, "old", "new password value")
        self.post.side_effect = None
        self.custom.side_effect = RuntimeError()
        with self.assertRaises(RuntimeError):
            change_password(UID, "old", "new password value")
        self.update.assert_not_called()


@skipUnless(os.environ.get("FIREBASE_AUTH_EMULATOR_HOST"), "Requiere Firebase Auth Emulator local.")
class EmailRaceIntegrationTests(SimpleTestCase):
    """Concurrencia real del proveedor; nunca usa el proyecto de producción."""

    def setUp(self):
        host = os.environ["FIREBASE_AUTH_EMULATOR_HOST"]
        self.assertTrue(host.startswith(("127.0.0.1:", "localhost:")))
        self.project = os.environ.get("GCLOUD_PROJECT", "demo-swipehome-us6")
        self.assertTrue(self.project.startswith("demo-"))

    def test_concurrent_email_updates_have_one_winner_and_no_partial_name(self):
        app = initialize_app(options={"projectId": self.project}, name="us6-race")
        users = []
        try:
            for i in range(2):
                users.append(auth.create_user(email=f"race-{i}@example.com", display_name=f"Original {i}", app=app))
            barrier = Barrier(2)
            def update(index):
                barrier.wait(timeout=10)
                try:
                    auth.update_user(users[index].uid, email="race-target@example.com", display_name="Updated", app=app)
                    return 200
                except auth.EmailAlreadyExistsError:
                    return 409
            with ThreadPoolExecutor(max_workers=2) as pool:
                statuses = list(pool.map(update, range(2)))
            self.assertEqual(sorted(statuses), [200, 409])
            for index, status in enumerate(statuses):
                stored = auth.get_user(users[index].uid, app=app)
                self.assertEqual(stored.display_name, "Updated" if status == 200 else f"Original {index}")
                self.assertEqual(stored.email, "race-target@example.com" if status == 200 else f"race-{index}@example.com")
        finally:
            for user in users:
                auth.delete_user(user.uid, app=app)
            delete_app(app)

    def test_password_change_continuity_with_real_emulator_tokens(self):
        import requests
        from unittest.mock import MagicMock

        host = os.environ["FIREBASE_AUTH_EMULATOR_HOST"]
        # Exclusivamente loopback, sin claves ni tráfico al proyecto real.
        if not host.startswith(("127.0.0.1:", "localhost:")):
            self.fail("El emulador de las pruebas debe estar en loopback.")
        base = f"http://{host}/identitytoolkit.googleapis.com/v1/"
        app = initialize_app(options={"projectId": self.project}, name="us6-password")
        old, new = "Original password value", " New password value 🙂 "
        user = auth.create_user(email="password-integration@example.com", password=old, display_name="Ana", app=app)
        real_post = requests.post

        def post(action, payload):
            return real_post(base + action, params={"key": "demo-key"}, json=payload, timeout=10)

        try:
            signed_in = post("accounts:signInWithPassword", {
                "email": user.email, "password": old, "returnSecureToken": True,
            })
            self.assertEqual(signed_in.status_code, 200)
            snapshot = MagicMock(exists=True)
            snapshot.to_dict.return_value = {"name": "Ana", "email": user.email, "role": "BUYER"}
            with patch("accounts.repository._users") as users, patch("accounts.repository.is_session_revoked", return_value=False):
                users.return_value.document.return_value.get.return_value = snapshot
                with patch("accounts.authentication.get_app", return_value=app), patch("accounts.repository.get_app", return_value=app), patch("accounts.passwords.get_app", return_value=app):
                    with patch.dict(os.environ, {"FIREBASE_WEB_API_KEY": "demo-key"}):
                        with patch("accounts.passwords.requests.post", side_effect=lambda url, **kwargs: real_post(base + "accounts:signInWithPassword", **kwargs)):
                            response = self.client.post(
                                "/api/auth/me/password",
                                json.dumps({"current_password": old, "new_password": new}),
                                content_type="application/json",
                                HTTP_AUTHORIZATION="Bearer " + signed_in.json()["idToken"],
                            )
                    self.assertEqual(response.status_code, 200, response.content)
                    self.assertNotIn("passwordHash", response.json())
                    self.assertNotIn(old, response.content.decode())
                    self.assertNotIn(new.strip(), response.content.decode())
                    exchange = post("accounts:signInWithCustomToken", {
                        "token": response.json()["custom_token"], "returnSecureToken": True,
                    })
                    self.assertEqual(exchange.status_code, 200)
                    me = self.client.get("/api/auth/me", HTTP_AUTHORIZATION="Bearer " + exchange.json()["idToken"])
                    self.assertEqual(me.status_code, 200)
                    self.assertEqual(me.json()["uid"], user.uid)
            self.assertEqual(post("accounts:signInWithPassword", {
                "email": user.email, "password": old, "returnSecureToken": True,
            }).status_code, 400)
            self.assertEqual(post("accounts:signInWithPassword", {
                "email": user.email, "password": new, "returnSecureToken": True,
            }).status_code, 200)
        finally:
            auth.delete_user(user.uid, app=app)
            delete_app(app)


@skipUnless(
    os.environ.get("FIREBASE_AUTH_EMULATOR_HOST") and os.environ.get("FIRESTORE_EMULATOR_HOST"),
    "Requiere Firebase Auth y Firestore Emulators locales.",
)
class ProfileSessionIntegrationTests(SimpleTestCase):
    """Pruebas de API con Auth y Firestore aislados en emuladores loopback."""

    def setUp(self):
        self.auth_host = os.environ["FIREBASE_AUTH_EMULATOR_HOST"]
        self.firestore_host = os.environ["FIRESTORE_EMULATOR_HOST"]
        for host in (self.auth_host, self.firestore_host):
            self.assertTrue(host.startswith(("127.0.0.1:", "localhost:")))
        self.project = os.environ.get("GCLOUD_PROJECT", "demo-swipehome-us4")
        self.assertTrue(self.project.startswith("demo-"))
        self.app = initialize_app(
            options={"projectId": self.project}, name="us6-profile-" + UID
        )
        self.db = firestore.Client(
            project=self.project, credentials=AnonymousCredentials()
        )
        self.enterContext(patch("accounts.authentication.get_app", return_value=self.app))
        self.enterContext(patch("accounts.repository.get_app", return_value=self.app))
        self.enterContext(patch("accounts.profile_views.get_app", return_value=self.app))
        self.enterContext(patch("accounts.passwords.get_app", return_value=self.app))
        self.enterContext(patch("accounts.repository.firestore.client", return_value=self.db))
        self.users = []
        self.addCleanup(self.cleanup_emulator_data)

    def cleanup_emulator_data(self):
        for user in self.users:
            self.db.collection("users").document(user.uid).delete()
            auth.delete_user(user.uid, app=self.app)
        delete_app(self.app)
        self.db.close()

    def create_account(self, role, number):
        email = f"us68-{number}@example.com"
        password = "Original password value"
        user = auth.create_user(
            email=email, password=password, display_name=f"Nombre {number}", app=self.app
        )
        self.users.append(user)
        self.db.collection("users").document(user.uid).create({
            "name": f"Nombre {number}", "email": email, "role": role,
        })
        return user, email, password

    def sign_in(self, email, password):
        import requests

        base = f"http://{self.auth_host}/identitytoolkit.googleapis.com/v1/"
        response = requests.post(
            base + "accounts:signInWithPassword",
            params={"key": "demo-key"},
            json={"email": email, "password": password, "returnSecureToken": True},
            timeout=10,
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["idToken"]

    @staticmethod
    def authenticated_client(token):
        client = Client(enforce_csrf_checks=True)
        client.defaults["HTTP_AUTHORIZATION"] = "Bearer " + token
        return client

    def test_buyer_and_seller_read_and_update_only_their_current_profile(self):
        for number, role in enumerate(("BUYER", "SELLER"), start=1):
            user, email, password = self.create_account(role, number)
            token = self.sign_in(email, password)
            client = self.authenticated_client(token)

            initial = client.get("/api/auth/me")
            self.assertEqual(initial.status_code, 200)
            self.assertEqual(initial.json(), {
                "uid": user.uid, "name": f"Nombre {number}",
                "email": email, "role": role,
            })

            response = client.patch(
                "/api/auth/me",
                json.dumps({"name": f"  Perfil {number}  ", "email": f"  {email.upper()}  "}),
                content_type="application/json",
            )
            self.assertEqual(response.status_code, 200, response.content)
            self.assertEqual(
                {key: response.json()[key] for key in ("uid", "name", "email", "role")},
                {"uid": user.uid, "name": f"Perfil {number}", "email": email, "role": role},
            )
            self.assertTrue(response.json()["custom_token"])
            after = client.get("/api/auth/me")
            self.assertEqual(after.status_code, 200)
            self.assertEqual(after.json()["name"], f"Perfil {number}")
            self.assertEqual(after.json()["role"], role)
            relogin = self.authenticated_client(self.sign_in(email, password))
            persisted = relogin.get("/api/auth/me")
            self.assertEqual(persisted.status_code, 200)
            self.assertEqual(persisted.json()["name"], f"Perfil {number}")

    def test_concurrent_profile_email_updates_have_one_winner_without_partial_write(self):
        accounts = [self.create_account("BUYER", i) for i in (3, 4)]
        clients = [
            self.authenticated_client(self.sign_in(email, password))
            for _, email, password in accounts
        ]
        barrier = Barrier(2)

        def update(index):
            barrier.wait(timeout=10)
            return clients[index].patch(
                "/api/auth/me",
                json.dumps({
                    "name": f"Concurrent {index}",
                    "email": "  Shared-Profile@example.com  ",
                }),
                content_type="application/json",
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(update, range(2)))
        self.assertCountEqual([response.status_code for response in responses], [200, 409])
        winner = next(index for index, response in enumerate(responses) if response.status_code == 200)
        loser = 1 - winner

        for index, (user, original_email, _) in enumerate(accounts):
            stored = auth.get_user(user.uid, app=self.app)
            if index == winner:
                self.assertEqual(stored.email, "shared-profile@example.com")
                self.assertEqual(stored.display_name, f"Concurrent {index}")
            else:
                self.assertEqual(stored.email, original_email)
                self.assertEqual(stored.display_name, f"Nombre {index + 3}")
            self.assertNotIn("passwordHash", responses[index].content.decode())

    def test_injected_profile_write_failure_leaves_auth_profile_unchanged(self):
        user, email, password = self.create_account("SELLER", 5)
        token = self.sign_in(email, password)
        client = self.authenticated_client(token)

        with patch(
            "accounts.repository.auth.update_user",
            side_effect=RuntimeError("internal provider detail"),
        ):
            with self.assertLogs("accounts.profile_views", level="ERROR") as logs:
                response = client.patch(
                    "/api/auth/me",
                    json.dumps({"name": "No debe guardarse"}),
                    content_type="application/json",
                )
        self.assertEqual(response.status_code, 500)
        self.assertNotIn("internal provider detail", response.content.decode())
        self.assertNotIn("internal provider detail", "\n".join(logs.output))
        stored = auth.get_user(user.uid, app=self.app)
        self.assertEqual(stored.display_name, "Nombre 5")
        self.assertEqual(stored.email, email)
        self.assertEqual(client.get("/api/auth/me").status_code, 200)

    def test_logout_revokes_old_token_idempotently_without_affecting_other_account(self):
        first, email, password = self.create_account("BUYER", 6)
        other, other_email, other_password = self.create_account("SELLER", 7)
        first_client = self.authenticated_client(self.sign_in(email, password))
        other_client = self.authenticated_client(self.sign_in(other_email, other_password))

        before = first_client.get("/api/auth/me")
        self.assertEqual(before.status_code, 200)
        auth_time = auth.verify_id_token(
            first_client.defaults["HTTP_AUTHORIZATION"].split(" ", 1)[1],
            app=self.app,
        )["auth_time"]
        self.assertEqual(first_client.get("/api/auth/logout").status_code, 405)
        self.assertEqual(first_client.post("/api/auth/logout").status_code, 204)
        self.assertEqual(first_client.get("/api/auth/me").status_code, 401)
        self.assertEqual(first_client.post("/api/auth/logout").status_code, 204)
        revocation = repository._revocation_document(first.uid, auth_time).get()
        self.assertTrue(revocation.exists)
        self.assertEqual(revocation.to_dict(), {"revoked": True})
        self.assertEqual(other_client.get("/api/auth/me").status_code, 200)
