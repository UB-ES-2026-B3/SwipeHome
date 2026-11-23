"""Integración real US4. Solo emuladores loopback con proyecto demo aislado."""
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from unittest import skipUnless
from unittest.mock import patch
from uuid import uuid4

from django.test import Client, SimpleTestCase
from firebase_admin import auth, delete_app, initialize_app
from google.api_core.exceptions import AlreadyExists
from google.auth.credentials import AnonymousCredentials
from google.cloud import firestore
from google.cloud.firestore_v1.transaction import Transaction

from accounts import repository
from properties.test_discovery import STAMP, listing

PROJECT = "demo-swipehome-us4"


@skipUnless(os.environ.get("FIRESTORE_EMULATOR_HOST"), "Requiere Firestore Emulator local.")
class FirestoreDecisionTests(SimpleTestCase):
    def setUp(self):
        host = os.environ["FIRESTORE_EMULATOR_HOST"]
        if not host.startswith(("127.0.0.1:", "localhost:")):
            self.fail("Solo se permiten emuladores loopback.")
        self.db = firestore.Client(project=PROJECT, credentials=AnonymousCredentials())
        self.addCleanup(self.db.close)
        self.prefix = uuid4().hex
        self.auth_time = int(self.prefix[:12], 16)
        # Colecciones únicas por test: jamás se borran colecciones ni datos ajenos.
        self.collections = {name: self.prefix + "_" + name.lower() for name in (
            "LISTINGS_COLLECTION", "SWIPES_COLLECTION", "MATCHES_COLLECTION", "NOTIFICATIONS_COLLECTION",
        )}
        for name, collection in self.collections.items():
            self.enterContext(patch.object(repository, name, collection))
        self.enterContext(patch("accounts.repository.get_app"))
        self.enterContext(patch("accounts.authentication.get_app"))
        self.enterContext(patch("accounts.repository.firestore.client", return_value=self.db))
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
        self.seed("home")

    def collection(self, name):
        return self.db.collection(self.collections[name.upper() + "_COLLECTION"])

    def seed(self, identifier, **changes):
        self.collection("listings").document(identifier).create(listing(**changes))

    def post(self, value="LIKE", uid="buyer", identifier="home", client=None):
        return (client or self.client).post(
            f"/api/inmuebles/{identifier}/decision", json.dumps({"decision": value}),
            content_type="application/json", HTTP_AUTHORIZATION="Bearer " + uid,
        )

    def explore(self, uid="buyer", **query):
        return self.client.get("/api/inmuebles/explorar", query, HTTP_AUTHORIZATION="Bearer " + uid)

    def notices(self, uid="seller", **query):
        return self.client.get("/api/notificaciones", query, HTTP_AUTHORIZATION="Bearer " + uid)

    def candidates(self, uid="seller", **query):
        return self.client.get("/api/matches/candidatos", query, HTTP_AUTHORIZATION="Bearer " + uid)

    def matches(self, uid="buyer", **query):
        return self.client.get("/api/matches", query, HTTP_AUTHORIZATION="Bearer " + uid)

    def transition(self, decision_id, value, uid="seller", client=None):
        return (client or self.client).post(
            f"/api/matches/candidaturas/{decision_id}/decision", json.dumps({"decision": value}),
            content_type="application/json", HTTP_AUTHORIZATION="Bearer " + uid,
        )

    def rows(self, name):
        return list(self.collection(name).stream())

    def counts(self):
        return tuple(len(self.rows(name)) for name in ("swipes", "matches", "notifications"))

    def test_all_three_endpoints_enforce_roles_without_persisting_changes(self):
        seller = Client(enforce_csrf_checks=True)
        buyer = Client(enforce_csrf_checks=True)
        self.assertEqual(
            seller.get("/api/inmuebles/explorar", HTTP_AUTHORIZATION="Bearer seller").status_code,
            403,
        )
        self.assertEqual(
            seller.post(
                "/api/inmuebles/home/decision",
                '{"decision":"LIKE"}',
                content_type="application/json",
                HTTP_AUTHORIZATION="Bearer seller",
            ).status_code,
            403,
        )
        self.assertEqual(
            buyer.get("/api/notificaciones", HTTP_AUTHORIZATION="Bearer buyer").status_code,
            200,
        )
        self.assertEqual(seller.get("/api/inmuebles/explorar").status_code, 401)
        self.assertEqual(
            seller.post(
                "/api/inmuebles/home/decision",
                '{"decision":"LIKE"}',
                content_type="application/json",
            ).status_code,
            401,
        )
        self.assertEqual(buyer.get("/api/notificaciones").status_code, 401)
        self.assertEqual(self.counts(), (0, 0, 0))

    def test_buyer_and_seller_can_read_only_their_own_notifications(self):
        for identifier, recipient, message in (
            ("buyer-confirmation", "buyer", "El propietario confirmó el interés."),
            ("seller-interest", "seller", "Un comprador mostró interés."),
            ("other-interest", "seller2", "Aviso de otra cuenta."),
        ):
            self.collection("notifications").document(identifier).create({
                "recipient_uid": recipient, "type": "MATCH", "message": message,
                "created_at": STAMP,
            })

        buyer = self.notices(uid="buyer")
        seller = self.notices(uid="seller")
        self.assertEqual(buyer.status_code, 200, buyer.content)
        self.assertEqual(seller.status_code, 200, seller.content)
        self.assertEqual([row["id"] for row in buyer.json()["items"]], ["buyer-confirmation"])
        self.assertEqual([row["id"] for row in seller.json()["items"]], ["seller-interest"])
        self.assertEqual(buyer.json()["items"][0]["message"], "El propietario confirmó el interés.")
        buyer_created_at = buyer.json()["items"][0]["created_at"]
        self.assertTrue(buyer_created_at.startswith("2026-11-08T00:00:00"))
        self.assertTrue(buyer_created_at.endswith("Z"))
        self.assertEqual(
            self.client.get("/api/notificaciones?uid=seller", HTTP_AUTHORIZATION="Bearer buyer").status_code,
            400,
        )
        self.assertEqual(
            self.client.get(
                "/api/notificaciones?recipient_uid=buyer", HTTP_AUTHORIZATION="Bearer seller"
            ).status_code,
            400,
        )
        self.assertEqual(len(self.rows("notifications")), 3)
        self.assertEqual(self.rows("swipes"), [])
        self.assertEqual(self.rows("matches"), [])

    def test_like_creates_one_pending_candidate_without_confirming_a_match(self):
        response = self.post()
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["decision"]["seller_decision"], "PENDING")
        self.assertIsNone(response.json()["match"])
        self.assertEqual(self.counts(), (1, 0, 0))
        decision = self.rows("swipes")[0]
        self.assertEqual(decision.id, response.json()["decision"]["id"])
        self.assertEqual(decision.to_dict()["value"], "LIKE")
        self.assertEqual(decision.to_dict()["seller_uid"], "seller")
        self.assertEqual(decision.to_dict()["seller_decision"], "PENDING")
        self.assertEqual(self.candidates().json()["items"][0]["buyer"]["id"], "buyer")
        self.assertEqual(self.matches().json()["items"], [])
        self.assertTrue(self.collection("listings").document("home").get().to_dict()["published"])

    def test_pass_creates_only_decision_and_no_notice(self):
        response = self.post("PASS")
        self.assertEqual(response.status_code, 201, response.content)
        self.assertIsNone(response.json()["match"])
        self.assertEqual(self.counts(), (1, 0, 0))
        self.assertEqual(self.notices().json(), {"items": [], "next_cursor": None})

    def test_same_decision_retries_return_identical_records(self):
        for value in ("LIKE", "PASS"):
            with self.subTest(value=value):
                self.seed(value)
                first = self.post(value, identifier=value)
                before = self.counts()
                second = self.post(value, identifier=value)
                self.assertEqual((first.status_code, second.status_code), (201, 200))
                self.assertEqual(first.json(), second.json())
                self.assertEqual(self.counts(), before)

    def test_both_conflict_directions_preserve_all_committed_records(self):
        for first, second in (("LIKE", "PASS"), ("PASS", "LIKE")):
            self.seed(first)
            self.assertEqual(self.post(first, identifier=first).status_code, 201)
            before = {name: [(s.id, s.to_dict()) for s in self.rows(name)]
                      for name in ("swipes", "matches", "notifications")}
            self.assertEqual(self.post(second, identifier=first).status_code, 409)
            after = {name: [(s.id, s.to_dict()) for s in self.rows(name)] for name in before}
            self.assertEqual(before, after)

    def test_missing_unpublished_and_incomplete_listings_have_no_side_effects(self):
        self.seed("draft", published=False)
        self.seed("partial", photos=[])
        for identifier in ("missing", "draft", "partial"):
            self.assertEqual(self.post(identifier=identifier).status_code, 404)
        self.assertEqual(self.counts(), (0, 0, 0))

    def test_each_staged_write_failure_rolls_back_entire_operation(self):
        original = Transaction.create
        def fail(transaction, reference, data):
            if reference.parent.id == self.collection("swipes").id:
                raise RuntimeError("private credentials SQL")
            return original(transaction, reference, data)
        with patch.object(Transaction, "create", new=fail):
            response = self.post()
        self.assertEqual(response.status_code, 500)
        self.assertNotIn("private", response.content.decode())
        self.assertEqual(self.counts(), (0, 0, 0))
        self.assertEqual(self.post().status_code, 201)

        decision_id = self.rows("swipes")[0].id
        original_update = Transaction.update
        def fail_accept(transaction, reference, field_updates):
            if reference.parent.id == self.collection("swipes").id:
                raise RuntimeError("private credentials SQL")
            return original_update(transaction, reference, field_updates)
        with patch.object(Transaction, "update", new=fail_accept):
            response = self.transition(decision_id, "ACCEPT")
            self.assertEqual(response.status_code, 500)
            self.assertNotIn("private", response.content.decode())
        decision = self.collection("swipes").document(decision_id).get().to_dict()
        self.assertEqual(decision["seller_decision"], "PENDING")
        self.assertEqual(self.counts(), (1, 0, 0))

    def test_rejected_commit_does_not_persist_any_staged_document(self):
        # Un create con precondición falsa fuerza un rechazo REAL de todo el commit.
        guard = self.collection("listings").document("home")
        original = Transaction.create
        def reject(transaction, reference, data):
            result = original(transaction, reference, data)
            if reference.parent.id == self.collection("swipes").id:
                original(transaction, guard, {"invalid": True})
            return result
        with patch.object(Transaction, "create", new=reject):
            self.assertEqual(self.post().status_code, 500)
        self.assertEqual(self.counts(), (0, 0, 0))
        self.assertEqual(guard.get().to_dict()["title"], listing()["title"])

    def test_document_create_uniqueness_is_enforced_by_firestore(self):
        self.assertEqual(self.post().status_code, 201)
        decision = self.rows("swipes")[0]
        self.assertEqual(self.transition(decision.id, "ACCEPT").status_code, 201)
        for name in ("swipes", "matches", "notifications"):
            snapshot = self.rows(name)[0]
            with self.assertRaises(AlreadyExists):
                snapshot.reference.create(snapshot.to_dict())
        self.assertEqual(self.counts(), (1, 1, 1))

    def test_inconsistent_origin_and_missing_match_never_return_success(self):
        self.assertEqual(self.post().status_code, 201)
        decision = self.rows("swipes")[0]
        original = decision.to_dict()
        decision.reference.update({"seller_uid": "foreign"})
        self.assertEqual(self.transition(decision.id, "ACCEPT").status_code, 404)
        decision.reference.set(original)
        self.assertEqual(self.transition(decision.id, "ACCEPT").status_code, 201)
        match = self.rows("matches")[0]
        original_match = match.to_dict()
        match.reference.update({"decision_id": "wrong"})
        self.assertEqual(self.transition(decision.id, "ACCEPT").status_code, 500)
        match.reference.set(original_match)
        self.assertEqual(self.counts(), (1, 1, 1))

    def test_pass_with_corrupt_match_is_rejected_and_not_promoted(self):
        self.assertEqual(self.post("PASS").status_code, 201)
        decision = self.rows("swipes")[0]
        self.collection("matches").document(decision.id).create({
            "buyer_uid": "buyer", "listing_id": "home", "decision_id": decision.id, "created_at": STAMP,
        })
        self.assertEqual(self.post("PASS").status_code, 500)
        self.assertEqual(self.post("LIKE").status_code, 409)
        self.assertEqual(decision.reference.get().to_dict()["value"], "PASS")

    def concurrent(self, values):
        barrier = Barrier(len(values))
        def send(value):
            barrier.wait(timeout=15)
            response = self.post(value, client=Client(enforce_csrf_checks=True))
            return response.status_code, response.json()
        with ThreadPoolExecutor(max_workers=len(values)) as executor:
            return list(executor.map(send, values))

    def test_simultaneous_identical_likes_converge_to_same_pending_candidate(self):
        responses = self.concurrent(["LIKE"] * 3)
        self.assertEqual(sorted(code for code, _ in responses), [200, 200, 201], responses)
        self.assertTrue(all(body["match"] is None for _, body in responses))
        self.assertEqual(self.counts(), (1, 0, 0))
        self.assertEqual(len(self.candidates().json()["items"]), 1)

    def test_simultaneous_identical_passes_converge(self):
        responses = self.concurrent(["PASS"] * 3)
        self.assertEqual(sorted(code for code, _ in responses), [200, 200, 201], responses)
        self.assertEqual(self.counts(), (1, 0, 0))

    def test_simultaneous_contradictory_decisions_have_one_winner(self):
        responses = self.concurrent(["LIKE", "PASS"])
        self.assertEqual(sorted(code for code, _ in responses), [201, 409], responses)
        winner = next(body["decision"]["value"] for code, body in responses if code == 201)
        self.assertEqual(self.rows("swipes")[0].to_dict()["value"], winner)
        self.assertEqual(self.counts(), (1, 0, 0))

    def test_two_buyers_create_independent_matches_with_same_home(self):
        self.assertEqual(self.post(uid="buyer").status_code, 201)
        self.assertEqual(self.post(uid="buyer2").status_code, 201)
        candidates = self.candidates().json()["items"]
        self.assertEqual({row["buyer"]["id"] for row in candidates}, {"buyer", "buyer2"})
        for candidate in candidates:
            self.assertEqual(self.transition(candidate["id"], "ACCEPT").status_code, 201)
        self.assertEqual(self.counts(), (2, 2, 2))
        self.assertEqual(len(self.matches("buyer").json()["items"]), 1)
        self.assertEqual(len(self.matches("buyer2").json()["items"]), 1)
        self.assertEqual(len(self.matches("seller").json()["items"]), 2)
        self.assertEqual([row["id"] for row in self.explore(uid="buyer3").json()["items"]], ["home"])

    def test_accept_and_reject_are_persistent_idempotent_and_independent(self):
        self.seed("second")
        self.assertEqual(self.post().status_code, 201)
        self.assertEqual(self.post(identifier="second").status_code, 201)
        candidates = {row["listing"]["id"]: row for row in self.candidates().json()["items"]}

        accepted = self.transition(candidates["home"]["id"], "ACCEPT")
        self.assertEqual(accepted.status_code, 201, accepted.content)
        original_match_date = self.rows("matches")[0].to_dict()["created_at"]
        original_decision_date = self.rows("swipes")[0].to_dict()["seller_decided_at"]
        retried = self.transition(candidates["home"]["id"], "ACCEPT")
        self.assertEqual(retried.status_code, 200, retried.content)
        self.assertEqual(self.rows("matches")[0].to_dict()["created_at"], original_match_date)
        self.assertEqual(self.rows("swipes")[0].to_dict()["seller_decided_at"], original_decision_date)
        self.assertEqual(self.transition(candidates["home"]["id"], "REJECT").status_code, 409)

        rejected = self.transition(candidates["second"]["id"], "REJECT")
        self.assertEqual(rejected.status_code, 201, rejected.content)
        self.assertIsNone(rejected.json()["match"])
        self.assertEqual(self.transition(candidates["second"]["id"], "REJECT").status_code, 200)
        self.assertEqual(self.transition(candidates["second"]["id"], "ACCEPT").status_code, 409)
        self.assertEqual({row["listing"]["id"] for row in self.candidates().json()["items"]}, set())
        self.assertEqual({row["listing"]["id"] for row in self.matches("buyer").json()["items"]}, {"home"})
        buyer_retry = self.post(uid="buyer", identifier="second")
        self.assertEqual(buyer_retry.status_code, 200, buyer_retry.content)
        self.assertEqual(buyer_retry.json()["decision"]["seller_decision"], "REJECT")
        self.assertIsNone(buyer_retry.json()["match"])
        self.assertEqual(self.counts(), (2, 1, 1))

    def test_candidates_and_matches_are_scoped_by_verified_owner_and_role(self):
        self.seed("other-owner", seller_uid="seller2")
        self.assertEqual(self.post().status_code, 201)
        self.assertEqual(self.post(identifier="other-owner").status_code, 201)
        candidates = {row["listing"]["id"]: row for row in self.candidates().json()["items"]}
        foreign = next(row for row in self.rows("swipes") if row.to_dict()["listing_id"] == "home")
        self.assertEqual(self.transition(foreign.id, "ACCEPT", uid="seller2").status_code, 404)
        self.assertEqual(self.transition(foreign.id, "ACCEPT", uid="buyer").status_code, 403)
        self.assertEqual({row["listing"]["id"] for row in self.candidates(uid="seller2").json()["items"]},
                         {"other-owner"})
        self.assertEqual(self.transition(candidates["home"]["id"], "ACCEPT").status_code, 201)
        self.assertEqual({row["listing"]["id"] for row in self.matches("buyer").json()["items"]}, {"home"})
        self.assertEqual(self.matches("buyer2").json()["items"], [])
        self.assertEqual(self.matches("seller2").json()["items"], [])

    def test_simultaneous_accept_and_reject_have_one_atomic_winner(self):
        self.assertEqual(self.post().status_code, 201)
        decision_id = self.rows("swipes")[0].id
        barrier = Barrier(2)

        def send(value):
            barrier.wait(timeout=15)
            response = self.transition(
                decision_id, value, client=Client(enforce_csrf_checks=True),
            )
            return response.status_code, response.json()

        with ThreadPoolExecutor(max_workers=2) as executor:
            responses = list(executor.map(send, ("ACCEPT", "REJECT")))
        self.assertEqual(sorted(status for status, _ in responses), [201, 409], responses)
        final = self.collection("swipes").document(decision_id).get().to_dict()
        self.assertIn(final["seller_decision"], {"ACCEPT", "REJECT"})
        self.assertEqual(len(self.rows("matches")), 1 if final["seller_decision"] == "ACCEPT" else 0)
        self.assertEqual(len(self.rows("notifications")), 1 if final["seller_decision"] == "ACCEPT" else 0)

    def test_accept_creation_failures_roll_back_decision_match_and_notice(self):
        self.assertEqual(self.post().status_code, 201)
        decision_id = self.rows("swipes")[0].id
        original = Transaction.create
        for failed_collection in ("matches", "notifications"):
            def fail(transaction, reference, data):
                if reference.parent.id == self.collection(failed_collection).id:
                    raise RuntimeError("private credentials SQL")
                return original(transaction, reference, data)
            with self.subTest(stage=failed_collection), patch.object(Transaction, "create", new=fail):
                response = self.transition(decision_id, "ACCEPT")
            self.assertEqual(response.status_code, 500)
            self.assertNotIn("private", response.content.decode())
            self.assertEqual(
                self.collection("swipes").document(decision_id).get().to_dict()["seller_decision"],
                "PENDING",
            )
            self.assertEqual(self.counts(), (1, 0, 0))

    def test_match_and_candidate_lists_paginate_and_return_empty_distinctly(self):
        self.seed("second")
        self.assertEqual(self.candidates().json(), {"items": [], "next_cursor": None})
        self.assertEqual(self.post().status_code, 201)
        self.assertEqual(self.post(identifier="second").status_code, 201)
        page = self.candidates(limit="1").json()
        self.assertEqual(len(page["items"]), 1)
        self.assertIsNotNone(page["next_cursor"])
        last = self.candidates(limit="1", cursor=page["next_cursor"]).json()
        self.assertEqual(len(last["items"]), 1)
        self.assertIsNone(last["next_cursor"])
        self.assertEqual(self.matches().json(), {"items": [], "next_cursor": None})

    def test_explore_excludes_only_own_decisions_and_preserves_all_photos(self):
        for identifier in ("liked", "passed", "foreign", "draft", "partial"):
            self.seed(identifier, published=identifier != "draft", photos=[] if identifier == "partial" else listing()["photos"])
        self.assertEqual(self.post(identifier="liked").status_code, 201)
        self.assertEqual(self.post("PASS", identifier="passed").status_code, 201)
        self.assertEqual(self.post(identifier="foreign", uid="buyer2").status_code, 201)
        response = self.explore().json()
        self.assertEqual([row["id"] for row in response["items"]], ["home", "foreign"])
        self.assertEqual(response["items"][0]["photos"], listing()["photos"])
        self.assertEqual(response["items"][0]["price"], "950.50")

    def test_pagination_ties_previous_page_decisions_and_last_page(self):
        for identifier in ("a", "b", "c", "d", "e"):
            self.seed(identifier)
        self.seed("older", created_at=STAMP - timedelta(days=1))
        first = self.explore(limit="2").json()
        self.assertEqual([r["id"] for r in first["items"]], ["home", "e"])
        for item in first["items"]:
            self.assertEqual(self.post("PASS", identifier=item["id"]).status_code, 201)
        # Incluir una publicación más nueva no cambia la continuación.
        self.seed("newer", created_at=STAMP + timedelta(days=1))
        second = self.explore(limit="2", cursor=first["next_cursor"]).json()
        self.assertEqual([r["id"] for r in second["items"]], ["d", "c"])
        third = self.explore(limit="2", cursor=second["next_cursor"]).json()
        self.assertEqual([r["id"] for r in third["items"]], ["b", "a"])
        last = self.explore(limit="2", cursor=third["next_cursor"]).json()
        self.assertEqual([r["id"] for r in last["items"]], ["older"])
        self.assertIsNone(last["next_cursor"])

    def test_scan_multiple_batches_of_decided_homes_without_skip_or_n_plus_one(self):
        batch = self.db.batch()
        for i in range(45):
            identifier = f"z{i:02}"
            batch.create(self.collection("listings").document(identifier), listing())
            batch.create(self.collection("swipes").document(repository.decision_key("buyer", identifier)), {
                "buyer_uid": "buyer", "listing_id": identifier, "value": "PASS", "created_at": STAMP,
            })
        batch.commit()
        self.seed("a")
        self.seed("b")
        with patch.object(self.db, "get_all", wraps=self.db.get_all) as reads:
            first = self.explore(limit="2").json()
        self.assertEqual([r["id"] for r in first["items"]], ["home", "b"])
        self.assertEqual(reads.call_count, 3)  # 3 lotes, no 48 consultas individuales.
        last = self.explore(limit="2", cursor=first["next_cursor"]).json()
        self.assertEqual([r["id"] for r in last["items"]], ["a"])
        self.assertIsNone(last["next_cursor"])

    def test_empty_and_exact_limit_pages_have_no_next_cursor(self):
        self.assertIsNone(self.explore(limit="1").json()["next_cursor"])
        self.assertEqual(self.post("PASS").status_code, 201)
        self.assertEqual(self.explore().json(), {"items": [], "next_cursor": None})

    def test_private_confirmation_notices_include_buyer_and_home(self):
        self.seed("foreign", seller_uid="seller2")
        self.seed("second")
        self.assertEqual(self.post().status_code, 201)
        self.assertEqual(self.post(identifier="second").status_code, 201)
        self.assertEqual(self.post(identifier="foreign", uid="buyer2").status_code, 201)
        for snapshot in self.rows("notifications"):
            self.assertEqual(snapshot.to_dict()["recipient_uid"], "buyer")
        for candidate in self.rows("swipes"):
            owner = "seller2" if candidate.to_dict()["listing_id"] == "foreign" else "seller"
            self.assertEqual(self.transition(candidate.id, "ACCEPT", uid=owner).status_code, 201)
        first = self.notices(uid="buyer", limit="1").json()
        second = self.notices(uid="buyer", limit="1", cursor=first["next_cursor"]).json()
        items = first["items"] + second["items"]
        self.assertEqual([row["id"] for row in items], sorted([row["id"] for row in items], reverse=True))
        self.assertIsNone(second["next_cursor"])
        self.assertEqual({row["listing"]["id"] for row in items}, {"home", "second"})
        self.assertEqual({row["buyer"]["id"] for row in items}, {"buyer"})
        for row in items:
            self.assertEqual(row["message"], "El propietario ha confirmado tu interés.")
            self.assertTrue(row["created_at"].endswith("Z"))
            self.assertEqual(row["listing"]["title"], listing()["title"])
            self.assertTrue(self.collection("matches").document(row["match_id"]).get().exists)
        self.assertEqual(len(self.notices(uid="buyer2").json()["items"]), 1)
        self.assertEqual(self.notices(uid="seller").json()["items"], [])
        self.assertEqual(self.notices(uid="seller2").json()["items"], [])
        self.assertEqual(self.notices(recipient_uid="seller2").status_code, 400)
        self.assertEqual(self.notices(uid="buyer2", cursor=first["next_cursor"]).status_code, 400)

    def test_legacy_notices_are_preserved_without_fabricated_match(self):
        self.collection("notifications").document("legacy").create({
            "recipient_uid": "seller", "type": "INFO", "message": "Histórico", "created_at": STAMP,
        })
        response = self.notices()
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("match_id", response.json()["items"][0])
        self.assertEqual(self.counts(), (0, 0, 1))

    def test_decisions_survive_logout_new_session_and_new_database_client(self):
        self.assertEqual(self.post().status_code, 201)
        headers = {"HTTP_AUTHORIZATION": "Bearer buyer"}
        self.assertEqual(self.client.post("/api/auth/logout", **headers).status_code, 204)
        self.assertEqual(self.post().status_code, 401)
        self.auth_time += 1
        fresh = firestore.Client(project=PROJECT, credentials=AnonymousCredentials())
        try:
            with patch("accounts.repository.firestore.client", return_value=fresh):
                self.assertEqual(self.post().status_code, 200)
                self.assertEqual(self.explore().json(), {"items": [], "next_cursor": None})
                self.assertEqual(self.notices().json()["items"], [])
                candidate_id = self.candidates().json()["items"][0]["id"]
                self.assertEqual(self.transition(candidate_id, "ACCEPT").status_code, 201)
                self.assertEqual(len(self.matches("buyer").json()["items"]), 1)
                self.assertEqual(len(self.notices(uid="buyer").json()["items"]), 1)
        finally:
            fresh.close()


@skipUnless(os.environ.get("FIRESTORE_EMULATOR_HOST") and os.environ.get("FIREBASE_AUTH_EMULATOR_HOST"),
            "Requiere Firestore y Auth Emulator locales.")
class FirebaseFlowTests(SimpleTestCase):
    def test_real_registration_login_publication_like_logout_and_relogin(self):
        import requests
        from properties.tests import VALID, jpeg

        for key in ("FIRESTORE_EMULATOR_HOST", "FIREBASE_AUTH_EMULATOR_HOST"):
            self.assertTrue(os.environ[key].startswith(("127.0.0.1:", "localhost:")))
        app = initialize_app(options={"projectId": PROJECT}, name="us4-" + uuid4().hex)
        self.addCleanup(delete_app, app)
        db = firestore.Client(project=PROJECT, credentials=AnonymousCredentials())
        self.addCleanup(db.close)
        for target in ("accounts.views.get_app", "accounts.authentication.get_app", "accounts.repository.get_app"):
            self.enterContext(patch(target, return_value=app))
        self.enterContext(patch("accounts.repository.firestore.client", return_value=db))
        # Storage es el único proveedor simulado en este recorrido.
        container = self.enterContext(patch("accounts.repository.get_container_client"))
        container.return_value.get_blob_client.return_value.url = "https://example.com/foto.jpg"
        client = Client(enforce_csrf_checks=True)
        suffix = uuid4().hex
        users = {}
        tokens = {}
        for role in ("SELLER", "BUYER"):
            payload = {"name": "Test " + role, "email": f"{role.lower()}-{suffix}@example.com",
                       "password": "Test password value 123!", "role": role}
            registered = client.post("/api/auth/register", json.dumps(payload), content_type="application/json")
            self.assertEqual(registered.status_code, 201, registered.content)
            users[role] = registered.json()
            self.addCleanup(auth.delete_user, users[role]["uid"], app=app)
            tokens[role] = self.login(payload["email"], payload["password"], requests)
        published = client.post("/api/inmuebles", {**VALID, "photos": [jpeg()]},
                                HTTP_AUTHORIZATION="Bearer " + tokens["SELLER"])
        self.assertEqual(published.status_code, 201, published.content)
        identifier = published.json()["id"]
        url = f"/api/inmuebles/{identifier}/decision"
        liked = client.post(url, '{"decision":"LIKE"}', content_type="application/json",
                            HTTP_AUTHORIZATION="Bearer " + tokens["BUYER"])
        self.assertEqual(liked.status_code, 201, liked.content)
        candidates = client.get(
            "/api/matches/candidatos", HTTP_AUTHORIZATION="Bearer " + tokens["SELLER"]
        )
        self.assertEqual(candidates.status_code, 200, candidates.content)
        self.assertEqual(len(candidates.json()["items"]), 1)
        candidate_id = candidates.json()["items"][0]["id"]
        self.assertEqual(client.post(
            f"/api/matches/candidaturas/{candidate_id}/decision", '{"decision":"ACCEPT"}',
            content_type="application/json", HTTP_AUTHORIZATION="Bearer " + tokens["SELLER"],
        ).status_code, 201)
        self.assertEqual(client.post("/api/auth/logout",
            HTTP_AUTHORIZATION="Bearer " + tokens["BUYER"]).status_code, 204)
        self.assertEqual(client.post(url, '{"decision":"LIKE"}', content_type="application/json",
            HTTP_AUTHORIZATION="Bearer " + tokens["BUYER"]).status_code, 401)
        time.sleep(1.05)  # auth_time tiene precisión de segundos; evita la revocación compartida US6.
        token = self.login(users["BUYER"]["email"], "Test password value 123!", requests)
        repeated = Client(enforce_csrf_checks=True).post(
            url, '{"decision":"LIKE"}', content_type="application/json", HTTP_AUTHORIZATION="Bearer " + token,
        )
        self.assertEqual(repeated.status_code, 200, repeated.content)
        self.assertEqual(repeated.json()["decision"]["id"], liked.json()["decision"]["id"])
        self.assertIsNotNone(repeated.json()["match"])
        notices = client.get("/api/notificaciones", HTTP_AUTHORIZATION="Bearer " + token)
        self.assertEqual(notices.status_code, 200, notices.content)
        self.assertEqual(len(notices.json()["items"]), 1)
        buyer_notice = notices.json()["items"][0]
        self.assertEqual(buyer_notice["message"], "El propietario ha confirmado tu interés.")
        self.assertTrue(buyer_notice["created_at"].endswith("Z"))

        self.assertEqual(client.post(
            "/api/auth/logout", HTTP_AUTHORIZATION="Bearer " + tokens["SELLER"]
        ).status_code, 204)
        self.assertEqual(client.get(
            "/api/notificaciones", HTTP_AUTHORIZATION="Bearer " + tokens["SELLER"]
        ).status_code, 401)
        time.sleep(1.05)
        seller_token = self.login(
            users["SELLER"]["email"], "Test password value 123!", requests
        )
        persisted_notice = client.get(
            "/api/notificaciones", HTTP_AUTHORIZATION="Bearer " + seller_token
        )
        self.assertEqual(persisted_notice.status_code, 200, persisted_notice.content)
        self.assertEqual(persisted_notice.json()["items"], [])

    def test_published_multi_photo_listings_survive_full_buyer_flow(self):
        import requests
        from types import SimpleNamespace
        from properties.tests import VALID, jpeg

        app = initialize_app(options={"projectId": PROJECT}, name="us410-" + uuid4().hex)
        self.addCleanup(delete_app, app)
        db = firestore.Client(project=PROJECT, credentials=AnonymousCredentials())
        self.addCleanup(db.close)
        prefix = "us410_" + uuid4().hex
        for collection in ("LISTINGS_COLLECTION", "SWIPES_COLLECTION", "MATCHES_COLLECTION", "NOTIFICATIONS_COLLECTION"):
            self.enterContext(patch.object(repository, collection, prefix + "_" + collection.lower()))
        for target in ("accounts.views.get_app", "accounts.authentication.get_app", "accounts.repository.get_app"):
            self.enterContext(patch(target, return_value=app))
        self.enterContext(patch("accounts.repository.firestore.client", return_value=db))
        photo_urls = [f"https://example.com/{uuid4().hex}.jpg" for _ in range(4)]
        urls = iter(photo_urls)
        container = self.enterContext(patch("accounts.repository.get_container_client"))
        container.return_value.get_blob_client.side_effect = lambda name: SimpleNamespace(
            url=next(urls), upload_blob=lambda *args, **kwargs: None,
        )

        client = Client(enforce_csrf_checks=True)
        registered_users = {"SELLER": [], "BUYER": []}
        tokens = {}
        for role in ("SELLER", "BUYER", "BUYER"):
            email = f"{role.lower()}-{uuid4().hex}@example.com"
            payload = {
                "name": f"Test {role}", "email": email,
                "password": "Test password value 123!", "role": role,
            }
            registered = client.post("/api/auth/register", json.dumps(payload), content_type="application/json")
            self.assertEqual(registered.status_code, 201, registered.content)
            uid = registered.json()["uid"]
            self.addCleanup(auth.delete_user, uid, app=app)
            self.addCleanup(db.collection("users").document(uid).delete)
            registered_users[role].append({"email": email, "uid": uid})
            tokens.setdefault(role, []).append(self.login(email, payload["password"], requests))

        seller_token = tokens["SELLER"][0]
        published = []
        for title in ("Piso para LIKE", "Piso para PASS"):
            response = client.post(
                "/api/inmuebles",
                {**VALID, "title": title, "photos": [jpeg("first.jpg"), jpeg("second.jpg")]},
                HTTP_AUTHORIZATION="Bearer " + seller_token,
            )
            self.assertEqual(response.status_code, 201, response.content)
            published.append(response.json()["id"])

        first_page = client.get(
            "/api/inmuebles/explorar?limit=20",
            HTTP_AUTHORIZATION="Bearer " + tokens["BUYER"][0],
        )
        self.assertEqual(first_page.status_code, 200, first_page.content)
        listings_by_id = {item["id"]: item for item in first_page.json()["items"]}
        self.assertEqual(set(listings_by_id), set(published))
        self.assertEqual(listings_by_id[published[0]]["photos"], photo_urls[:2])
        self.assertEqual(listings_by_id[published[0]]["title"], "Piso para LIKE")
        self.assertEqual(listings_by_id[published[0]]["street"], VALID["street"])
        self.assertEqual(listings_by_id[published[0]]["price"], "950.50")
        self.assertEqual(listings_by_id[published[0]]["people"], 3)

        def decide(token, listing_id, value):
            return client.post(
                f"/api/inmuebles/{listing_id}/decision",
                json.dumps({"decision": value}),
                content_type="application/json",
                HTTP_AUTHORIZATION="Bearer " + token,
            )

        liked = decide(tokens["BUYER"][0], published[0], "LIKE")
        passed = decide(tokens["BUYER"][0], published[1], "PASS")
        self.assertEqual(liked.status_code, 201, liked.content)
        self.assertEqual(liked.json()["decision"]["seller_decision"], "PENDING")
        self.assertIsNone(liked.json()["match"])
        self.assertEqual(passed.status_code, 201, passed.content)
        self.assertIsNone(passed.json()["match"])

        candidates = client.get("/api/matches/candidatos", HTTP_AUTHORIZATION="Bearer " + seller_token)
        self.assertEqual(candidates.status_code, 200, candidates.content)
        self.assertEqual(len(candidates.json()["items"]), 1)
        candidate_id = candidates.json()["items"][0]["id"]
        self.assertEqual(candidates.json()["items"][0]["listing"]["id"], published[0])
        self.assertEqual(candidates.json()["items"][0]["buyer"]["id"], registered_users["BUYER"][0]["uid"])
        self.assertEqual(client.get(
            "/api/matches", HTTP_AUTHORIZATION="Bearer " + tokens["BUYER"][0],
        ).json()["items"], [])
        self.assertEqual(client.post(
            f"/api/matches/candidaturas/{candidate_id}/decision", '{"decision":"ACCEPT"}',
            content_type="application/json", HTTP_AUTHORIZATION="Bearer " + seller_token,
        ).status_code, 201)
        buyer_matches = client.get(
            "/api/matches", HTTP_AUTHORIZATION="Bearer " + tokens["BUYER"][0],
        )
        seller_matches = client.get("/api/matches", HTTP_AUTHORIZATION="Bearer " + seller_token)
        self.assertEqual(len(buyer_matches.json()["items"]), 1)
        self.assertEqual(len(seller_matches.json()["items"]), 1)

        self.assertEqual(client.post(
            "/api/auth/logout", HTTP_AUTHORIZATION="Bearer " + tokens["BUYER"][0],
        ).status_code, 204)
        time.sleep(1.05)
        relogged_token = self.login(
            registered_users["BUYER"][0]["email"], "Test password value 123!", requests,
        )
        relogged_client = Client(enforce_csrf_checks=True)
        self.assertEqual(relogged_client.get(
            "/api/inmuebles/explorar", HTTP_AUTHORIZATION="Bearer " + relogged_token,
        ).json(), {"items": [], "next_cursor": None})
        repeated_like = decide(relogged_token, published[0], "LIKE")
        self.assertEqual(repeated_like.status_code, 200, repeated_like.content)
        self.assertEqual(repeated_like.json()["decision"]["id"], liked.json()["decision"]["id"])
        self.assertEqual(repeated_like.json()["match"]["id"], buyer_matches.json()["items"][0]["id"])

        second_buyer = client.get(
            "/api/inmuebles/explorar", HTTP_AUTHORIZATION="Bearer " + tokens["BUYER"][1],
        )
        self.assertEqual({item["id"] for item in second_buyer.json()["items"]}, set(published))
        second_like = decide(tokens["BUYER"][1], published[0], "LIKE")
        second_rejected = decide(tokens["BUYER"][1], published[1], "LIKE")
        self.assertEqual(second_like.status_code, 201, second_like.content)
        self.assertEqual(second_rejected.status_code, 201, second_rejected.content)
        seller_candidates = client.get(
            "/api/matches/candidatos", HTTP_AUTHORIZATION="Bearer " + seller_token,
        )
        self.assertEqual(len(seller_candidates.json()["items"]), 2)
        candidates_by_listing = {
            item["listing"]["id"]: item for item in seller_candidates.json()["items"]
        }
        self.assertEqual(set(candidates_by_listing), set(published))
        self.assertTrue(all(
            item["buyer"]["id"] == registered_users["BUYER"][1]["uid"]
            for item in candidates_by_listing.values()
        ))
        self.assertEqual(client.post(
            f"/api/matches/candidaturas/{candidates_by_listing[published[0]]['id']}/decision",
            '{"decision":"ACCEPT"}', content_type="application/json",
            HTTP_AUTHORIZATION="Bearer " + seller_token,
        ).status_code, 201)
        accepted_retry = client.post(
            f"/api/matches/candidaturas/{candidates_by_listing[published[0]]['id']}/decision",
            '{"decision":"ACCEPT"}', content_type="application/json",
            HTTP_AUTHORIZATION="Bearer " + seller_token,
        )
        self.assertEqual(accepted_retry.status_code, 200, accepted_retry.content)
        self.assertEqual(
            accepted_retry.json()["match"]["id"],
            candidates_by_listing[published[0]]["id"],
        )
        self.assertEqual(client.post(
            f"/api/matches/candidaturas/{candidates_by_listing[published[1]]['id']}/decision",
            '{"decision":"REJECT"}', content_type="application/json",
            HTTP_AUTHORIZATION="Bearer " + seller_token,
        ).status_code, 201)
        self.assertEqual(client.get(
            "/api/matches/candidatos", HTTP_AUTHORIZATION="Bearer " + seller_token,
        ).json()["items"], [])
        second_matches = client.get("/api/matches", HTTP_AUTHORIZATION="Bearer " + tokens["BUYER"][1])
        self.assertEqual(len(second_matches.json()["items"]), 1)
        self.assertNotEqual(second_matches.json()["items"][0]["id"], buyer_matches.json()["items"][0]["id"])
        self.assertEqual(second_matches.json()["items"][0]["listing"]["id"], published[0])
        seller_matches = client.get("/api/matches", HTTP_AUTHORIZATION="Bearer " + seller_token)
        self.assertEqual(
            {(item["buyer"]["id"], item["listing"]["id"]) for item in seller_matches.json()["items"]},
            {
                (registered_users["BUYER"][0]["uid"], published[0]),
                (registered_users["BUYER"][1]["uid"], published[0]),
            },
        )

    def login(self, email, password, requests):
        host = os.environ["FIREBASE_AUTH_EMULATOR_HOST"]
        response = requests.post(
            f"http://{host}/identitytoolkit.googleapis.com/v1/accounts:signInWithPassword",
            params={"key": "demo-key"}, json={"email": email, "password": password, "returnSecureToken": True},
            timeout=15,
        )
        self.assertEqual(response.status_code, 200)
        return response.json()["idToken"]
