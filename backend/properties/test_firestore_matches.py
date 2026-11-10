import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Barrier
from unittest import skipUnless
from unittest.mock import patch
from uuid import uuid4

from django.test import Client, SimpleTestCase
from google.auth.credentials import AnonymousCredentials
from google.cloud import firestore

from accounts import repository
from properties.test_discovery import STAMP, listing

PROJECT = "demo-swipehome-us4"


@skipUnless(os.environ.get("FIRESTORE_EMULATOR_HOST"), "Requiere Firestore Emulator local.")
class FirestoreMatchesTests(SimpleTestCase):
    def setUp(self):
        host = os.environ["FIRESTORE_EMULATOR_HOST"]
        if not host.startswith(("127.0.0.1:", "localhost:")):
            self.fail("Solo se permiten emuladores loopback.")
        self.db = firestore.Client(project=PROJECT, credentials=AnonymousCredentials())
        self.addCleanup(self.db.close)
        self.prefix = uuid4().hex
        self.auth_time = int(self.prefix[:12], 16)
        self.collections = {name: self.prefix + "_" + name.lower() for name in (
            "LISTINGS_COLLECTION", "SWIPES_COLLECTION", "MATCHES_COLLECTION", "NOTIFICATIONS_COLLECTION",
        )}
        for name, collection in self.collections.items():
            self.enterContext(patch.object(repository, name, collection))
        self.enterContext(patch("accounts.repository.get_app"))
        self.enterContext(patch("accounts.authentication.get_app"))
        self.enterContext(patch("properties.match_service.get_app"))
        self.enterContext(patch("accounts.repository.firestore.client", return_value=self.db))
        self.enterContext(patch("properties.match_service.firestore.client", return_value=self.db))
        self.verify = self.enterContext(patch(
            "accounts.authentication.auth.verify_id_token",
            side_effect=lambda token, **kwargs: {"uid": token, "auth_time": self.auth_time},
        ))
        self.profile = self.enterContext(patch(
            "accounts.repository.get_user_profile",
            side_effect=lambda uid: {"role": "SELLER" if uid.startswith("seller") else "BUYER",
                                     "name": "Name " + uid, "uid": uid},
        ))
        self.client = Client(enforce_csrf_checks=True)
        self.seed("home-1", seller_uid="seller-1")

    def collection(self, name):
        return self.db.collection(self.collections[name.upper() + "_COLLECTION"])

    def seed(self, identifier, **changes):
        self.collection("listings").document(identifier).create(listing(**changes))

    def swipe(self, value="LIKE", uid="buyer-1", identifier="home-1"):
        return self.client.post(
            f"/api/inmuebles/{identifier}/decision",
            json.dumps({"decision": value}),
            content_type="application/json",
            HTTP_AUTHORIZATION="Bearer " + uid,
        )

    def decide_seller(self, match_id, value="LIKE", uid="seller-1", client=None):
        return (client or self.client).post(
            f"/api/matches/{match_id}/decision-vendedor",
            json.dumps({"decision": value}),
            content_type="application/json",
            HTTP_AUTHORIZATION="Bearer " + uid,
        )

    def candidates(self, uid="seller-1", **query):
        return self.client.get("/api/candidatos", query, HTTP_AUTHORIZATION="Bearer " + uid)

    def matches(self, uid="buyer-1", **query):
        return self.client.get("/api/matches", query, HTTP_AUTHORIZATION="Bearer " + uid)

    def test_buyer_like_creates_pending_match_and_notice(self):
        res = self.swipe("LIKE")
        self.assertEqual(res.status_code, 201)
        data = res.json()
        self.assertIsNotNone(data["match"])
        self.assertEqual(data["match"]["status"], "PENDING")
        match_id = data["match"]["id"]

        # Check in Firestore
        match_doc = self.collection("matches").document(match_id).get().to_dict()
        self.assertEqual(match_doc["status"], "PENDING")
        self.assertEqual(match_doc["seller_uid"], "seller-1")
        self.assertEqual(match_doc["buyer_uid"], "buyer-1")

        # Appears in seller candidates
        res_cand = self.candidates()
        self.assertEqual(res_cand.status_code, 200)
        items = res_cand.json()["items"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["id"], match_id)
        self.assertEqual(items[0]["status"], "PENDING")
        self.assertEqual(items[0]["buyer"]["id"], "buyer-1")

        # Does NOT appear in buyer matches yet (only confirmed)
        res_m = self.matches("buyer-1")
        self.assertEqual(res_m.status_code, 200)
        self.assertEqual(res_m.json()["items"], [])

    def test_seller_confirms_candidate_and_mutuality(self):
        swipe_res = self.swipe("LIKE")
        match_id = swipe_res.json()["match"]["id"]

        # Seller confirms with LIKE
        confirm_res = self.decide_seller(match_id, "LIKE")
        self.assertEqual(confirm_res.status_code, 200)
        self.assertEqual(confirm_res.json()["status"], "CONFIRMED")
        self.assertIn("confirmed_at", confirm_res.json())

        # No longer in candidates
        self.assertEqual(self.candidates().json()["items"], [])

        # Now appears in BUYER matches
        buyer_matches = self.matches("buyer-1").json()["items"]
        self.assertEqual(len(buyer_matches), 1)
        self.assertEqual(buyer_matches[0]["id"], match_id)
        self.assertEqual(buyer_matches[0]["status"], "CONFIRMED")
        self.assertEqual(buyer_matches[0]["listing"]["id"], "home-1")
        self.assertIn("price", buyer_matches[0]["listing"])

        # Now appears in SELLER matches
        seller_matches = self.matches("seller-1").json()["items"]
        self.assertEqual(len(seller_matches), 1)
        self.assertEqual(seller_matches[0]["id"], match_id)
        self.assertEqual(seller_matches[0]["status"], "CONFIRMED")
        self.assertEqual(seller_matches[0]["buyer"]["id"], "buyer-1")

    def test_seller_rejects_candidate(self):
        swipe_res = self.swipe("LIKE")
        match_id = swipe_res.json()["match"]["id"]

        reject_res = self.decide_seller(match_id, "PASS")
        self.assertEqual(reject_res.status_code, 200)
        self.assertEqual(reject_res.json()["status"], "REJECTED")

        # Disappears from candidates
        self.assertEqual(self.candidates().json()["items"], [])

        # Does NOT appear in buyer matches
        self.assertEqual(self.matches("buyer-1").json()["items"], [])

    def test_seller_decision_idempotency_and_conflict(self):
        swipe_res = self.swipe("LIKE")
        match_id = swipe_res.json()["match"]["id"]

        # First confirm
        first = self.decide_seller(match_id, "LIKE")
        self.assertEqual(first.status_code, 200)

        # Retry confirm -> idempotent 200
        second = self.decide_seller(match_id, "LIKE")
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.json(), second.json())

        # Conflict: try to change to PASS -> 409
        conflict = self.decide_seller(match_id, "PASS")
        self.assertEqual(conflict.status_code, 409)

    def test_buyer_resending_like_preserves_confirmed_status(self):
        swipe_res = self.swipe("LIKE")
        match_id = swipe_res.json()["match"]["id"]

        # Seller confirms
        self.decide_seller(match_id, "LIKE")

        # Buyer retries LIKE
        retry = self.swipe("LIKE")
        self.assertEqual(retry.status_code, 200)
        self.assertEqual(retry.json()["match"]["status"], "CONFIRMED")

    def test_other_seller_cannot_decide_candidacy(self):
        swipe_res = self.swipe("LIKE")
        match_id = swipe_res.json()["match"]["id"]

        # seller-2 tries to decide on home-1 of seller-1 -> 404
        forbidden = self.decide_seller(match_id, "LIKE", uid="seller-2")
        self.assertEqual(forbidden.status_code, 404)

    def test_concurrent_seller_decisions_on_same_candidate(self):
        swipe_res = self.swipe("LIKE")
        match_id = swipe_res.json()["match"]["id"]

        barrier = Barrier(3)

        def make_decision(val):
            barrier.wait()
            c = Client(enforce_csrf_checks=True)
            return self.decide_seller(match_id, val, client=c)

        with ThreadPoolExecutor(max_workers=3) as pool:
            # 2 LIKEs and 1 PASS
            futures = [
                pool.submit(make_decision, "LIKE"),
                pool.submit(make_decision, "LIKE"),
                pool.submit(make_decision, "PASS"),
            ]
            responses = [f.result() for f in futures]

        statuses = [r.status_code for r in responses]
        # Exactly two 200s and one 409 (if LIKE won), or one 200, one 409, one 409 (if PASS won)
        self.assertIn(200, statuses)
        self.assertIn(409, statuses)

        final_match = self.collection("matches").document(match_id).get().to_dict()
        self.assertIn(final_match["status"], {"CONFIRMED", "REJECTED"})

    def test_candidate_pagination_stability_without_skips(self):
        # Create 3 homes and candidate swipes
        for i in range(1, 4):
            hid = f"home-multi-{i}"
            self.seed(hid, seller_uid="seller-1")
            self.swipe("LIKE", uid=f"buyer-{i}", identifier=hid)

        # Get page 1 with limit=2
        page1 = self.candidates(limit=2)
        self.assertEqual(page1.status_code, 200)
        p1_items = page1.json()["items"]
        self.assertEqual(len(p1_items), 2)
        cursor1 = page1.json()["next_cursor"]
        self.assertIsNotNone(cursor1)

        # Seller confirms candidate 1 on page 1
        self.decide_seller(p1_items[0]["id"], "LIKE")

        # Seller now requests page 2 with cursor from page 1
        page2 = self.candidates(cursor=cursor1, limit=2)
        self.assertEqual(page2.status_code, 200)
        p2_items = page2.json()["items"]
        # Candidate 3 must be returned on page 2 without being skipped!
        self.assertEqual(len(p2_items), 1)
