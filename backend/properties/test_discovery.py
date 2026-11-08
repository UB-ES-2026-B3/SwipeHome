"""US4: contratos HTTP, permisos y validación sin servicios externos."""
import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from django.core import signing
from django.test import Client, RequestFactory, SimpleTestCase
from firebase_admin import auth
from google.api_core.datetime_helpers import DatetimeWithNanoseconds

from accounts import repository
from accounts.notification_service import CURSOR_SALT as NOTIFICATION_SALT
from properties.discovery_service import CURSOR_SALT
from properties.discovery_views import explore_listings
from properties.serialization import listing_item, published_listing

STAMP = datetime(2026, 11, 8, tzinfo=timezone.utc)


def listing(**changes):
    return {
        "title": "Piso luminoso", "street": "Calle Mayor 1", "city": "Barcelona",
        "postal_code": "08001", "description": "Descripción del inmueble",
        "price_cents": 95050, "surface_hundredths": 6550,
        "bedrooms": 2, "bathrooms": 1, "people": 3, "shared_accommodation": False,
        "seller_uid": "seller", "photos": ["https://example.com/2.jpg", "https://example.com/1.jpg"],
        "published": True, "created_at": STAMP, **changes,
    }


class DiscoveryApiTests(SimpleTestCase):
    def setUp(self):
        self.enterContext(patch("accounts.authentication.get_app"))
        self.verify = self.enterContext(patch(
            "accounts.authentication.auth.verify_id_token",
            return_value={"uid": "buyer", "auth_time": 100},
        ))
        self.revoked = self.enterContext(patch("accounts.repository.is_session_revoked", return_value=False))
        self.profile = self.enterContext(patch(
            "accounts.repository.get_user_profile", return_value={"role": "BUYER", "name": "Ana"},
        ))
        self.pending = self.enterContext(patch("accounts.repository.get_pending_listings", return_value=[]))
        self.record = self.enterContext(patch("accounts.repository.record_decision", return_value=(
            {"id": "key", "buyer_uid": "buyer", "listing_id": "home", "value": "LIKE", "created_at": STAMP},
            {"id": "key", "decision_id": "key", "listing_id": "home", "created_at": STAMP}, True,
        )))
        self.client = Client(enforce_csrf_checks=True)

    def post(self, body=None, token="token", path="/api/inmuebles/home/decision", **kwargs):
        headers = {} if token is None else {"HTTP_AUTHORIZATION": "Bearer " + token}
        return self.client.post(path, json.dumps(body if body is not None else {"decision": "LIKE"}),
                                content_type="application/json", **headers, **kwargs)

    def get(self, query=None, token="token"):
        headers = {} if token is None else {"HTTP_AUTHORIZATION": "Bearer " + token}
        return self.client.get("/api/inmuebles/explorar", query or {}, **headers)

    def test_authentication_and_buyer_permissions_for_both_endpoints(self):
        for operation in (self.get, self.post):
            self.assertEqual(operation(token=None).status_code, 401)
            self.profile.return_value = {"role": "SELLER"}
            self.assertEqual(operation().status_code, 403)
            self.profile.return_value = None
            self.assertEqual(operation().status_code, 403)
            self.profile.return_value = {"role": "BUYER", "name": "Ana"}
        self.pending.assert_not_called()
        self.record.assert_not_called()

    def test_invalid_expired_revoked_and_cookie_only_requests_are_401(self):
        self.client.cookies["sessionid"] = "not-a-firebase-token"
        self.client.cookies["csrftoken"] = "a" * 32
        for operation in (self.get, self.post):
            self.assertEqual(operation(token=None).status_code, 401)
            for error in (auth.InvalidIdTokenError("hidden"), auth.ExpiredIdTokenError("hidden", None)):
                self.verify.side_effect = error
                self.assertEqual(operation().status_code, 401)
            self.verify.side_effect = None
            self.revoked.return_value = True
            self.assertEqual(operation().status_code, 401)
            self.revoked.return_value = False

    def test_firebase_bearer_post_with_csrf_checks_enabled_uses_verified_identity(self):
        # Este contrato no usa cookies: Django CSRF no se añade ni se desactiva.
        self.assertTrue(self.client.handler.enforce_csrf_checks)
        response = self.post()
        self.assertEqual(response.status_code, 201)
        self.record.assert_called_once_with("buyer", "home", "LIKE", buyer_name="Ana")
        self.assertEqual(response.json()["match"]["decision_id"], "key")
        self.assertIn("no-store", response["Cache-Control"])
        self.assertTrue(self.verify.call_args.kwargs["check_revoked"])

    def test_client_cannot_choose_buyer_or_owner(self):
        for field in ("buyer_uid", "seller_uid", "recipient_uid", "buyer", "owner"):
            self.assertEqual(self.post({"decision": "LIKE", field: "attacker"}).status_code, 400)
        self.record.assert_not_called()

    def test_invalid_json_types_values_and_content_types(self):
        for body in ({}, [], None, True, 1, "LIKE", {"decision": None}, {"decision": True},
                     {"decision": 1}, {"decision": []}, {"decision": {}}, {"decision": "like"},
                     {"decision": " LIKE"}, {"decision": "PASS "}, {"decision": ""}):
            response = self.client.post("/api/inmuebles/home/decision", json.dumps(body),
                                        content_type="application/json", HTTP_AUTHORIZATION="Bearer token")
            self.assertEqual(response.status_code, 400, repr(body))
        for body in (b"{", b"", b"\xff", b'{"decision":NaN}'):
            self.assertEqual(self.client.post("/api/inmuebles/home/decision", body,
                content_type="application/json", HTTP_AUTHORIZATION="Bearer token").status_code, 400)
        self.assertEqual(self.client.post("/api/inmuebles/home/decision", "decision=LIKE",
            content_type="text/plain", HTTP_AUTHORIZATION="Bearer token").status_code, 400)
        self.record.assert_not_called()

    def test_new_retry_pass_and_conflict_contracts(self):
        self.record.return_value = (*self.record.return_value[:2], False)
        response = self.post()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["match"]["id"], "key")
        decision = dict(self.record.return_value[0], value="PASS")
        self.record.return_value = (decision, None, True)
        response = self.post({"decision": "PASS"})
        self.assertEqual(response.status_code, 201)
        self.assertIsNone(response.json()["match"])
        self.record.side_effect = repository.DecisionConflict()
        self.assertEqual(self.post().status_code, 409)
        self.record.side_effect = repository.ListingNotFound()
        self.assertEqual(self.post().status_code, 404)

    def test_internal_failures_are_safe_for_both_endpoints(self):
        for dependency, operation in ((self.verify, self.get), (self.profile, self.post),
                                      (self.pending, self.get), (self.record, self.post)):
            dependency.side_effect = RuntimeError("secret_token password SQL traceback")
            response = operation()
            self.assertEqual(response.status_code, 500)
            for secret in ("secret_token", "password", "SQL", "traceback"):
                self.assertNotIn(secret, response.content.decode())
            dependency.side_effect = None

    def test_explore_default_max_empty_and_pagination(self):
        response = self.get()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"items": [], "next_cursor": None})
        self.pending.assert_called_with("buyer", limit=21, position=None)
        self.get({"limit": "50"})
        self.pending.assert_called_with("buyer", limit=51, position=None)
        stamp = DatetimeWithNanoseconds.from_rfc3339("2026-11-08T00:00:00.123456789Z")
        self.pending.return_value = [listing_item(i, listing(created_at=stamp)) for i in ("z", "y", "x")]
        response = self.get({"limit": "2"}).json()
        self.assertEqual([row["id"] for row in response["items"]], ["z", "y"])
        self.pending.return_value = [listing_item("x", listing(created_at=stamp))]
        last = self.get({"limit": "2", "cursor": response["next_cursor"]}).json()
        self.assertIsNone(last["next_cursor"])
        position = self.pending.call_args.kwargs["position"]
        self.assertEqual(position[0].nanosecond, 123456789)
        self.assertEqual(position[1], "y")

    def test_invalid_limits_queries_and_cross_resource_cursors(self):
        queries = ("limit=0", "limit=51", "limit=-1", "limit=1.5", "limit=abc", "limit=",
                   "limit=1&limit=2", "cursor=", "cursor=bad", "cursor=x&cursor=y",
                   "buyer_uid=attacker", "limit=%2020")
        for query in queries:
            self.assertEqual(self.client.get("/api/inmuebles/explorar?" + query,
                HTTP_AUTHORIZATION="Bearer token").status_code, 400, query)
        payload = {"uid": "buyer", "id": "x", "created_at": "2026-11-08T00:00:00Z"}
        for salt, data in ((NOTIFICATION_SALT, payload), (CURSOR_SALT, dict(payload, uid="other")),
                           (CURSOR_SALT, dict(payload, id="../x")),
                           (CURSOR_SALT, dict(payload, created_at="invalid"))):
            cursor = signing.dumps(data, salt=salt)
            self.assertEqual(self.get({"cursor": cursor}).status_code, 400)
        self.pending.assert_not_called()

    def test_request_user_is_overwritten_from_verified_token(self):
        request = RequestFactory().get("/api/inmuebles/explorar", HTTP_AUTHORIZATION="Bearer token")
        request.user = SimpleNamespace(uid="attacker", role="BUYER")
        self.assertEqual(explore_listings(request).status_code, 200)
        self.assertEqual(request.user.uid, "buyer")

    def test_methods_outside_contract_are_405(self):
        self.assertEqual(self.client.post("/api/inmuebles/explorar").status_code, 405)
        self.assertEqual(self.client.get("/api/inmuebles/home/decision").status_code, 405)


class ListingContractTests(SimpleTestCase):
    def test_all_public_fields_and_ordered_photos_without_internal_data(self):
        item = listing_item("home", listing(password="hidden", private="hidden"))
        self.assertEqual(set(item), {
            "id", "title", "street", "city", "postal_code", "description", "price", "surface",
            "bedrooms", "bathrooms", "people", "shared_accommodation", "photos", "created_at",
        })
        self.assertEqual(item["price"], "950.50")
        self.assertEqual(item["surface"], "65.50")
        self.assertEqual(item["photos"], listing()["photos"])
        self.assertNotIn("seller_uid", item)

    def test_partial_or_unpublished_listings_are_not_eligible(self):
        self.assertTrue(published_listing(listing()))
        for changes in ({"published": False}, {"published": 1}, {"photos": []},
                        {"photos": [""]}, {"created_at": None}, {"seller_uid": ""},
                        {"price_cents": True}, {"bathrooms": 0}, {"title": ""},
                        {"shared_accommodation": "No"}):
            self.assertFalse(published_listing(listing(**changes)), changes)


class RepositoryRetryTests(SimpleTestCase):
    def test_read_abort_and_create_collision_use_fresh_transactions(self):
        from unittest.mock import MagicMock
        from google.api_core.exceptions import Aborted, AlreadyExists

        for error in (Aborted("contention"), AlreadyExists("collision")):
            with self.subTest(error=type(error).__name__):
                client = MagicMock()
                first, second = object(), object()
                client.transaction.side_effect = [first, second]
                expected = ({"id": "existing"}, None, False)
                with patch("accounts.repository.get_app"), patch(
                    "accounts.repository.firestore.client", return_value=client,
                ), patch("accounts.repository._record_decision", side_effect=[error, expected]) as operation:
                    result = repository.record_decision("buyer", "home", "PASS", buyer_name="Ana")
                self.assertEqual(result, expected)
                self.assertIs(operation.call_args_list[0].args[0], first)
                self.assertIs(operation.call_args_list[1].args[0], second)

    def test_sdk_exhausted_abort_is_retried_but_unrelated_value_error_is_not(self):
        from unittest.mock import MagicMock
        from google.api_core.exceptions import Aborted

        error = ValueError("attempts exhausted")
        error.__cause__ = Aborted("contention")
        client = MagicMock()
        with patch("accounts.repository.get_app"), patch(
            "accounts.repository.firestore.client", return_value=client,
        ), patch("accounts.repository._record_decision", side_effect=[error, ("existing", None, False)]) as operation:
            self.assertEqual(repository.record_decision("buyer", "home", "PASS", buyer_name="Ana"),
                             ("existing", None, False))
            self.assertEqual(operation.call_count, 2)
        with patch("accounts.repository.get_app"), patch(
            "accounts.repository.firestore.client", return_value=client,
        ), patch("accounts.repository._record_decision", side_effect=ValueError("invalid data")) as operation:
            with self.assertRaises(ValueError):
                repository.record_decision("buyer", "home", "PASS", buyer_name="Ana")
            self.assertEqual(operation.call_count, 1)
