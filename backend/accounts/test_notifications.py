from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.core import signing
from django.http import QueryDict
from django.test import RequestFactory, SimpleTestCase
from firebase_admin import auth
from google.api_core.datetime_helpers import DatetimeWithNanoseconds

from . import repository
from .notification_service import CURSOR_SALT, InvalidNotificationQuery, parse_query
from .notification_views import notifications


class NotificationApiTests(SimpleTestCase):
    def setUp(self):
        self.enterContext(patch("accounts.authentication.get_app"))
        self.verify = self.enterContext(patch(
            "accounts.authentication.auth.verify_id_token",
            return_value={"uid": "buyer", "auth_time": 100},
        ))
        self.revoked = self.enterContext(patch("accounts.repository.is_session_revoked", return_value=False))
        self.profile = self.enterContext(patch(
            "accounts.repository.get_user_profile", return_value={"role": "SELLER", "name": "Seller"},
        ))
        self.read = self.enterContext(patch("accounts.repository.get_notifications", return_value=[]))
        self.writes = [self.enterContext(patch("accounts.repository." + name)) for name in (
            "create_user_profile", "create_listing", "update_user_profile", "revoke_session",
        )]

    def get(self, query=None, token="test-token"):
        headers = {} if token is None else {"HTTP_AUTHORIZATION": "Bearer " + token}
        return self.client.get("/api/notificaciones", query or {}, **headers)

    def row(self, identifier, stamp=None):
        return {"id": identifier, "type": "MATCH", "message": "Tienes un aviso.",
                "created_at": stamp or datetime(2026, 11, 6, tzinfo=timezone.utc),
                "password": "secret", "recipient_uid": "buyer"}

    def test_empty_seller_default_limit_buyer_forbidden_and_no_writes(self):
        response = self.get()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"items": [], "next_cursor": None})
        self.assertIn("no-store", response["Cache-Control"])
        self.read.assert_called_once_with("buyer", limit=21, position=None)
        self.profile.return_value = {"role": "BUYER"}
        self.assertEqual(self.get().status_code, 403)
        for write in self.writes:
            write.assert_not_called()

    def test_uses_verified_request_user(self):
        request = RequestFactory().get("/api/notificaciones", HTTP_AUTHORIZATION="Bearer test-token")
        request.user = SimpleNamespace(uid="attacker", role="SELLER")
        response = notifications(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(request.user.uid, "buyer")
        self.read.assert_called_once_with("buyer", limit=21, position=None)
        self.verify.assert_called_once()
        self.assertTrue(self.verify.call_args.kwargs["check_revoked"])

    def test_pagination_preserves_nanoseconds_and_whitelists_fields(self):
        stamp = DatetimeWithNanoseconds.from_rfc3339("2026-11-06T00:00:00.123456789Z")
        self.read.return_value = [self.row("z", stamp), self.row("y", stamp), self.row("x", stamp)]
        first = self.get({"limit": "2"}).json()
        self.assertEqual([row["id"] for row in first["items"]], ["z", "y"])
        self.assertEqual(set(first["items"][0]), {"id", "type", "message", "created_at"})
        self.assertEqual(first["items"][0]["created_at"], "2026-11-06T00:00:00.123456789Z")
        self.read.return_value = [self.row("x", stamp)]
        response = self.get({"limit": "2", "cursor": first["next_cursor"]})
        self.assertEqual(response.json()["next_cursor"], None)
        position = self.read.call_args.kwargs["position"]
        self.assertEqual(position[0].nanosecond, 123456789)
        self.assertEqual(position[1], "y")

    def test_exact_limit_has_no_next_cursor_and_maximum_is_50(self):
        self.read.return_value = [self.row(str(i)) for i in range(50)]
        response = self.get({"limit": "50"})
        self.assertEqual(len(response.json()["items"]), 50)
        self.assertIsNone(response.json()["next_cursor"])
        self.read.assert_called_once_with("buyer", limit=51, position=None)

    def test_invalid_limits_and_queries_do_not_read(self):
        for query in ("limit=0", "limit=51", "limit=-1", "limit=1.5", "limit=", "limit=abc",
                      "limit=999999999999999", "limit=1&limit=2", "cursor=", "cursor=x&cursor=y",
                      "uid=other", "recipient_uid=other", "cursor=invalid", "limit=%2020"):
            with self.subTest(query=query):
                self.assertEqual(self.client.get("/api/notificaciones?" + query,
                    HTTP_AUTHORIZATION="Bearer test-token").status_code, 400)
        self.read.assert_not_called()

    def test_foreign_and_tampered_cursor_rejected(self):
        self.read.return_value = [self.row("b"), self.row("a")]
        cursor = self.get({"limit": "1"}).json()["next_cursor"]
        self.read.reset_mock()
        self.assertEqual(self.get({"cursor": cursor + "tampered"}).status_code, 400)
        self.verify.return_value = {"uid": "other", "auth_time": 100}
        self.assertEqual(self.get({"cursor": cursor}).status_code, 400)
        self.read.assert_not_called()

    def test_missing_invalid_expired_and_revoked_sessions(self):
        self.assertEqual(self.get(token=None).status_code, 401)
        for error in (auth.InvalidIdTokenError("secret"), auth.ExpiredIdTokenError("secret", None),
                      auth.RevokedIdTokenError("secret")):
            self.verify.side_effect = error
            response = self.get()
            self.assertEqual(response.status_code, 401)
            self.assertEqual(response["WWW-Authenticate"], "Bearer")
        self.verify.side_effect = None
        self.revoked.return_value = True
        self.assertEqual(self.get().status_code, 401)
        self.read.assert_not_called()

    def test_internal_errors_are_generic_and_logged_without_secrets(self):
        for dependency in (self.verify, self.revoked, self.profile, self.read):
            with self.subTest(dependency=dependency):
                dependency.side_effect = RuntimeError("password=secret token=test-token internal traceback")
                with self.assertLogs("accounts", level="ERROR") as logs:
                    response = self.get()
                self.assertEqual(response.status_code, 500)
                exposed = response.content.decode() + " ".join(logs.output)
                for secret in ("password", "secret", "test-token", "traceback"):
                    self.assertNotIn(secret, exposed)
                dependency.side_effect = None

    def test_missing_profile_or_forbidden_role(self):
        for profile in (None, {"role": "ADMIN"}):
            self.profile.return_value = profile
            self.assertEqual(self.get().status_code, 403)
        self.read.assert_not_called()

    def test_other_methods_are_rejected(self):
        for method in ("post", "put", "patch", "delete", "head"):
            self.assertEqual(getattr(self.client, method)("/api/notificaciones").status_code, 405)
        self.read.assert_not_called()

    def test_malformed_signed_payloads_are_400(self):
        for payload in ([], {}, {"uid": "buyer", "id": "../x", "created_at": "bad"},
                        {"uid": "buyer", "id": "x", "created_at": 123},
                        {"uid": "buyer", "id": "x", "created_at": "bad"}):
            cursor = signing.dumps(payload, salt=CURSOR_SALT)
            with self.assertRaises(InvalidNotificationQuery):
                parse_query(QueryDict("cursor=" + cursor), "buyer")


class NotificationRepositoryTests(SimpleTestCase):
    def test_firestore_query_filters_orders_bounds_and_only_reads(self):
        with patch("accounts.repository.get_app"), patch("accounts.repository.firestore.client") as client:
            collection = client.return_value.collection.return_value
            query = MagicMock()
            collection.where.return_value = query
            query.order_by.return_value = query
            query.start_after.return_value = query
            query.limit.return_value = query
            stamp = DatetimeWithNanoseconds.from_rfc3339("2026-11-06T00:00:00.123456789Z")
            snapshot = MagicMock(id="a")
            snapshot.to_dict.return_value = {
                "recipient_uid": "buyer", "type": "MATCH", "message": "Aviso", "created_at": stamp,
                "password": "secret",
            }
            query.stream.return_value = [snapshot]
            result = repository.get_notifications("buyer", limit=21, position=(stamp, "b"))
            client.return_value.collection.assert_called_once_with("notifications")
            field_filter = collection.where.call_args.kwargs["filter"]
            self.assertEqual((field_filter.field_path, field_filter.op_string, field_filter.value),
                             ("recipient_uid", "==", "buyer"))
            self.assertEqual([call.args[0] for call in query.order_by.call_args_list],
                             ["created_at", "__name__"])
            for call in query.order_by.call_args_list:
                self.assertEqual(call.kwargs, {"direction": "DESCENDING"})
            query.start_after.assert_called_once_with({
                "created_at": stamp, "__name__": collection.document.return_value,
            })
            collection.document.assert_called_once_with("b")
            query.limit.assert_called_once_with(21)
            self.assertEqual(result, [{"id": "a", "type": "MATCH", "message": "Aviso", "created_at": stamp}])
            self.assertFalse({"create", "set", "update", "delete", "batch", "transaction"} &
                             {call[0].split(".")[-1] for call in client.mock_calls})

    def test_defensive_recipient_check_rejects_foreign_record(self):
        with patch("accounts.repository.get_app"), patch("accounts.repository.firestore.client") as client:
            query = client.return_value.collection.return_value.where.return_value
            query.order_by.return_value = query
            query.limit.return_value = query
            snapshot = MagicMock()
            snapshot.to_dict.return_value = {"recipient_uid": "other"}
            query.stream.return_value = [snapshot]
            with self.assertRaises(ValueError):
                repository.get_notifications("buyer", limit=21)
            query.start_after.assert_not_called()
