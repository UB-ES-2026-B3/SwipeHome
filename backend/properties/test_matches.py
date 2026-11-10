import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase
from google.api_core.datetime_helpers import DatetimeWithNanoseconds

from accounts import repository
from properties.match_service import MATCHES_SALT, CANDIDATES_SALT


class MatchesApiTests(SimpleTestCase):
    def setUp(self):
        self.enterContext(patch("accounts.authentication.get_app"))
        self.enterContext(patch("properties.match_service.get_app"))
        self.mock_client = self.enterContext(patch("properties.match_service.firestore.client"))
        self.verify = self.enterContext(patch(
            "accounts.authentication.auth.verify_id_token",
            return_value={"uid": "seller-1", "auth_time": 100},
        ))
        self.revoked = self.enterContext(patch("accounts.repository.is_session_revoked", return_value=False))
        self.profile = self.enterContext(patch(
            "accounts.repository.get_user_profile",
            return_value={"role": "SELLER", "name": "Propietario"},
        ))
        self.get_confirmed = self.enterContext(patch(
            "accounts.repository.get_confirmed_matches",
            return_value=[],
        ))
        self.get_cand = self.enterContext(patch(
            "accounts.repository.get_candidates",
            return_value=[],
        ))
        self.record_seller = self.enterContext(patch(
            "accounts.repository.record_seller_decision",
            return_value=({"id": "match-1", "status": "CONFIRMED", "decided_at": datetime.now(timezone.utc), "confirmed_at": datetime.now(timezone.utc)}, True),
        ))

    def get_matches(self, query=None, token="token"):
        headers = {} if token is None else {"HTTP_AUTHORIZATION": "Bearer " + token}
        return self.client.get("/api/matches", query or {}, **headers)

    def get_candidates(self, query=None, token="token"):
        headers = {} if token is None else {"HTTP_AUTHORIZATION": "Bearer " + token}
        return self.client.get("/api/candidatos", query or {}, **headers)

    def post_decision(self, match_id="match-1", body=None, token="token", content_type="application/json"):
        headers = {} if token is None else {"HTTP_AUTHORIZATION": "Bearer " + token}
        data = json.dumps(body if body is not None else {"decision": "LIKE"}) if content_type == "application/json" else body
        return self.client.post(
            f"/api/matches/{match_id}/decision-vendedor",
            data,
            content_type=content_type,
            **headers,
        )

    def test_authentication_required(self):
        self.assertEqual(self.get_matches(token=None).status_code, 401)
        self.assertEqual(self.get_candidates(token=None).status_code, 401)
        self.assertEqual(self.post_decision(token=None).status_code, 401)

    def test_candidates_forbidden_for_buyer(self):
        self.profile.return_value = {"role": "BUYER", "name": "Comprador"}
        self.assertEqual(self.get_candidates().status_code, 403)
        self.assertEqual(self.post_decision().status_code, 403)

    def test_matches_allowed_for_both_roles(self):
        self.profile.return_value = {"role": "BUYER", "name": "Comprador"}
        self.mock_client.return_value.get_all.return_value = []
        res_buyer = self.get_matches()
        self.assertEqual(res_buyer.status_code, 200)

        self.profile.return_value = {"role": "SELLER", "name": "Vendedor"}
        res_seller = self.get_matches()
        self.assertEqual(res_seller.status_code, 200)

    def test_matches_unknown_role_forbidden(self):
        self.profile.return_value = {"role": "ADMIN", "name": "Admin"}
        self.assertEqual(self.get_matches().status_code, 403)

    def test_empty_results_return_200(self):
        res = self.get_matches()
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json(), {"items": [], "next_cursor": None})

        res_cand = self.get_candidates()
        self.assertEqual(res_cand.status_code, 200)
        self.assertEqual(res_cand.json(), {"items": [], "next_cursor": None})

    def test_invalid_query_parameters(self):
        for invalid_param in ({"foo": "bar"}, {"limit": "0"}, {"limit": "51"}, {"limit": "abc"}):
            self.assertEqual(self.get_matches(invalid_param).status_code, 400)
            self.assertEqual(self.get_candidates(invalid_param).status_code, 400)

    def test_property_filter_validation(self):
        # Invalid format
        self.assertEqual(self.get_matches({"inmueble": "invalid/id"}).status_code, 400)
        self.assertEqual(self.get_candidates({"inmueble": ".."}).status_code, 400)

        # Unrelated property for seller
        snap = MagicMock()
        snap.exists = True
        snap.to_dict.return_value = {"seller_uid": "other-seller"}
        self.mock_client.return_value.collection.return_value.document.return_value.get.return_value = snap
        self.assertEqual(self.get_matches({"inmueble": "home-1"}).status_code, 403)
        self.assertEqual(self.get_candidates({"inmueble": "home-1"}).status_code, 403)

        # Related property for seller
        snap.to_dict.return_value = {"seller_uid": "seller-1"}
        self.assertEqual(self.get_matches({"inmueble": "home-1"}).status_code, 200)
        self.assertEqual(self.get_candidates({"inmueble": "home-1"}).status_code, 200)

    def test_seller_decision_payload_validation(self):
        # Missing content-type
        res = self.post_decision(content_type="text/plain", body="raw")
        self.assertEqual(res.status_code, 400)

        # Invalid bodies
        for bad in ({}, {"decision": "OTHER"}, {"decision": 123}, {"decision": "LIKE", "extra": 1}):
            self.assertEqual(self.post_decision(body=bad).status_code, 400)

        # Malformed match_id
        self.assertEqual(self.post_decision(match_id="in/valid").status_code, 404)

    def test_seller_decision_success_and_conflict_handling(self):
        now = datetime.now(timezone.utc)
        self.record_seller.return_value = ({"id": "m1", "status": "CONFIRMED", "decided_at": now, "confirmed_at": now}, True)
        res = self.post_decision(match_id="m1", body={"decision": "LIKE"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["status"], "CONFIRMED")

        # Conflict
        self.record_seller.side_effect = repository.DecisionConflict()
        res_conf = self.post_decision(match_id="m1", body={"decision": "PASS"})
        self.assertEqual(res_conf.status_code, 409)

        # Match not found
        self.record_seller.side_effect = repository.MatchNotFound()
        res_nf = self.post_decision(match_id="m-missing", body={"decision": "LIKE"})
        self.assertEqual(res_nf.status_code, 404)

    def test_internal_error_handling(self):
        self.get_cand.side_effect = RuntimeError("database connection crashed")
        self.assertEqual(self.get_candidates().status_code, 500)

        self.get_confirmed.side_effect = RuntimeError("database connection crashed")
        self.assertEqual(self.get_matches().status_code, 500)

        self.record_seller.side_effect = RuntimeError("database connection crashed")
        self.assertEqual(self.post_decision().status_code, 500)
