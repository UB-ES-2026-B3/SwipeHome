"""US9 HTTP and transactional integration tests (loopback emulators only)."""
import json
import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest import skipUnless
from unittest.mock import patch
from uuid import uuid4

from django.test import Client, SimpleTestCase
from firebase_admin import auth
from google.auth.credentials import AnonymousCredentials
from google.cloud import firestore

from accounts import repository as repo
from properties.test_discovery import listing


class ProposalHttpTests(SimpleTestCase):
    def setUp(self):
        self.enterContext(patch("accounts.authentication.get_app"))
        self.verify = self.enterContext(patch("accounts.authentication.auth.verify_id_token", return_value={"uid": "seller", "auth_time": 123}))
        self.enterContext(patch.object(repo, "is_session_revoked", return_value=False))
        self.profile = self.enterContext(patch.object(repo, "get_user_profile", return_value={"role": "SELLER", "name": "Name"}))
        self.client = Client(enforce_csrf_checks=True)

    def post(self, data, path="/api/propuestas", token="token"):
        return self.client.post(path, json.dumps(data), content_type="application/json",
                                **({"HTTP_AUTHORIZATION": "Bearer " + token} if token else {}))

    def test_authentication_roles_and_cookie_does_not_authenticate(self):
        self.assertEqual(self.post({}, token=None).status_code, 401)
        self.client.cookies["sessionid"] = "fake"
        self.assertEqual(self.post({}, token=None).status_code, 401)
        self.verify.side_effect = auth.InvalidIdTokenError("invalid")
        self.assertEqual(self.post({}).status_code, 401)
        self.verify.side_effect = None
        self.profile.return_value = {"role": "BUYER"}
        self.assertEqual(self.post({}).status_code, 403)
        self.assertEqual(self.post({}, "/api/propuestas/id/cancelar").status_code, 403)
        self.profile.return_value = {"role": "SELLER"}
        self.assertEqual(self.post({}, "/api/propuestas/id/aceptar").status_code, 403)

    def test_bad_bodies_and_safe_errors(self):
        for body in ([], {}, {"listing_id": "x", "match_id": "y", "request_id": []},
                     {"listing_id": "x", "match_id": "y", "request_id": "k", "buyer_uid": "fake"}):
            self.assertEqual(self.post(body).status_code, 400)
        data = {"listing_id": "x", "match_id": "y", "request_id": "k"}
        for error, status in ((repo.ProposalNotFound(), 404), (repo.DecisionConflict(), 409), (ValueError("secret"), 500)):
            with patch.object(repo, "create_proposal", side_effect=error):
                response = self.post(data)
                self.assertEqual(response.status_code, status)
                self.assertNotIn("secret", response.content.decode())


@skipUnless(os.environ.get("FIRESTORE_EMULATOR_HOST"), "Requires local Firestore emulator")
class ProposalFirestoreTests(SimpleTestCase):
    def setUp(self):
        self.assertTrue(os.environ["FIRESTORE_EMULATOR_HOST"].startswith(("127.0.0.1:", "localhost:")))
        self.db = firestore.Client(project="demo-swipehome-us4", credentials=AnonymousCredentials())
        self.addCleanup(self.db.close)
        prefix = uuid4().hex
        for name in ("LISTINGS", "SWIPES", "MATCHES", "NOTIFICATIONS", "PROPOSALS", "SELECTIONS", "PROPOSAL_REQUESTS", "SELECTION_EVENTS", "USERS"):
            self.enterContext(patch.object(repo, name + "_COLLECTION", prefix + name))
        self.enterContext(patch("accounts.repository.get_app"))
        self.enterContext(patch("accounts.repository.firestore.client", return_value=self.db))
        self.enterContext(patch("accounts.authentication.get_app"))
        self.enterContext(patch("properties.match_service.get_app"))
        self.enterContext(patch("accounts.authentication.auth.verify_id_token", side_effect=lambda token, **kw: {"uid": token, "auth_time": 123}))
        self.enterContext(patch.object(repo, "is_session_revoked", return_value=False))
        self.enterContext(patch.object(repo, "get_user_profile", side_effect=lambda uid: {"role": "SELLER" if uid.startswith("seller") else "BUYER", "name": "Name", "uid": uid}))
        self.client = Client(enforce_csrf_checks=True)
        self.col("LISTINGS").document("home").create(listing(seller_uid="seller"))
        self.match = self.candidate("buyer", confirm=True)

    def col(self, name):
        return self.db.collection(getattr(repo, name + "_COLLECTION"))

    def candidate(self, uid, confirm=False, home="home"):
        self.col("USERS").document(uid).set({"role": "BUYER", "name": uid})
        _, match, _ = repo.record_decision(uid, home, "LIKE", buyer_name=uid)
        if confirm:
            repo.record_seller_decision("seller", match["id"], "LIKE")
        return match["id"]

    def create(self, key="request", match=None, home="home", uid="seller"):
        return repo.create_proposal(uid, home, match or self.match, key)

    def resolve(self, proposal, status="ACCEPTED", uid="buyer"):
        return repo.resolve_proposal(uid, "SELLER" if status == "CANCELLED" else "BUYER", proposal["id"], status)

    def request(self, method, path, uid="seller", data=None):
        return getattr(self.client, method)(path, json.dumps(data) if data is not None else None,
                    content_type="application/json", HTTP_AUTHORIZATION="Bearer " + uid) if method != "get" else self.client.get(path, HTTP_AUTHORIZATION="Bearer " + uid)

    def test_accept_closes_preserves_matches_other_homes_and_notifies_privately(self):
        self.candidate("other")
        self.candidate("confirmed", confirm=True)
        self.col("LISTINGS").document("elsewhere").create(listing(seller_uid="seller"))
        other_home = self.candidate("buyer", home="elsewhere", confirm=True)
        proposal, created = self.create()
        self.assertTrue(created)
        self.assertEqual(repo.listing_availability(repo.get_listing("home")), "ACTIVE")
        self.resolve(proposal)
        self.assertEqual(repo.get_listing("home")["closure_reason"], "Alquiler acordado")
        self.assertEqual(repo.get_listing("home")["people"], 3)
        self.assertEqual(repo.get_filter_cities(), ["Barcelona"])
        self.assertEqual(self.col("MATCHES").document(other_home).get().to_dict()["status"], "CONFIRMED")
        self.assertEqual(self.col("MATCHES").document(self.match).get().to_dict()["status"], "CONFIRMED")
        self.assertEqual(repo.get_pending_listings("new", limit=10)[0]["id"], "elsewhere")
        with self.assertRaises(repo.DecisionConflict):
            repo.record_decision("new", "home", "LIKE", buyer_name="New")
        with self.assertRaises(repo.DecisionConflict):
            repo.record_seller_decision("seller", repo.decision_key("other", "home"), "LIKE")
        notices = [s.to_dict() for s in self.col("NOTIFICATIONS").stream() if s.to_dict()["type"] == "LISTING_CLOSED"]
        self.assertEqual({n["recipient_uid"] for n in notices}, {"other", "confirmed"})
        for notice in notices:
            self.assertFalse({"buyer_uid", "buyer_name", "match_id", "proposal_id", "selected_buyer_uid"} & set(notice))
        count = len(list(self.col("NOTIFICATIONS").stream()))
        self.resolve(proposal)
        repeated, created = self.create()
        self.assertFalse(created)
        self.assertEqual(repeated["status"], "ACCEPTED")
        self.assertEqual(count, len(list(self.col("NOTIFICATIONS").stream())))
        with self.assertRaises(repo.DecisionConflict):
            self.create("new")

    def test_reject_cancel_and_paused_release_lock(self):
        repo.update_listing("seller", "home", {"availability": "PAUSED"})
        for status, uid in (("REJECTED", "buyer"), ("CANCELLED", "seller")):
            proposal, _ = self.create(status)
            for change in ({"title": "changed"}, {"availability": "ACTIVE"}):
                with self.assertRaises(repo.DecisionConflict):
                    repo.update_listing("seller", "home", change)
            self.assertEqual(self.resolve(proposal, status, uid)["status"], status)
            self.resolve(proposal, status, uid)
            self.assertEqual(repo.listing_availability(repo.get_listing("home")), "PAUSED")
            repo.update_listing("seller", "home", {"title": "Updated"})
        with self.assertRaises(repo.DecisionConflict):
            self.resolve(proposal)
        self.assertEqual(len(list(self.col("PROPOSALS").stream())), 2)

    def test_ownership_query_detail_resolution_and_idempotency_content(self):
        proposal, _ = self.create()
        for uid, role in (("seller-other", "SELLER"), ("buyer-other", "BUYER")):
            self.assertEqual(repo.get_proposals(uid, role, limit=10), [])
            with self.assertRaises(repo.ProposalNotFound):
                repo.get_proposal(uid, role, proposal["id"])
            with self.assertRaises(repo.ProposalNotFound):
                repo.resolve_proposal(uid, role, proposal["id"], "CANCELLED" if role == "SELLER" else "ACCEPTED")
        for uid in ("seller", "buyer"):
            response = self.request("get", "/api/propuestas/" + proposal["id"], uid)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["listing"]["price"], "950.50")
            self.assertEqual(response.json()["seller"], {"id": "seller", "name": "Name"})
            self.assertEqual(len(self.request("get", "/api/propuestas", uid).json()["items"]), 1)
        self.assertEqual(self.request("get", "/api/propuestas/" + proposal["id"], "buyer-other").status_code, 404)
        other = self.candidate("other", confirm=True)
        with self.assertRaises(repo.DecisionConflict):
            self.create(match=other)
        with self.assertRaises(repo.ProposalNotFound):
            self.create(uid="seller-other")

    def race(self, *operations):
        barrier = Barrier(len(operations))
        def run(operation):
            barrier.wait(timeout=10)
            try:
                return operation()
            except repo.DecisionConflict:
                return "conflict"
        with ThreadPoolExecutor(max_workers=len(operations)) as pool:
            return list(pool.map(run, operations))

    def test_concurrent_creations_and_accept_cancel(self):
        results = self.race(lambda: self.create("a"), lambda: self.create("b"))
        self.assertEqual(results.count("conflict"), 1)
        proposal = next(r[0] for r in results if r != "conflict")
        results = self.race(lambda: self.resolve(proposal), lambda: self.resolve(proposal, "CANCELLED", "seller"))
        self.assertEqual(results.count("conflict"), 1)
        final = self.col("PROPOSALS").document(proposal["id"]).get().to_dict()
        self.assertIn(final["status"], {"ACCEPTED", "CANCELLED"})
        self.assertEqual(repo.listing_availability(repo.get_listing("home")) == "CLOSED", final["status"] == "ACCEPTED")

    def test_close_races_with_interest_and_match_confirmation(self):
        other = self.candidate("other")
        proposal, _ = self.create()
        self.race(lambda: self.resolve(proposal), lambda: repo.record_decision("new", "home", "LIKE", buyer_name="New"),
                  lambda: repo.record_seller_decision("seller", other, "LIKE"))
        self.assertEqual(repo.listing_availability(repo.get_listing("home")), "CLOSED")
        recipients = {s.to_dict()["recipient_uid"] for s in self.col("NOTIFICATIONS").stream() if s.to_dict()["type"] == "LISTING_CLOSED"}
        self.assertIn("other", recipients)
        if self.col("MATCHES").document(repo.decision_key("new", "home")).get().exists:
            self.assertIn("new", recipients)

    def test_notification_failure_rolls_back_all_acceptance_writes(self):
        proposal, _ = self.create()
        original = repo._proposal_notice
        def fail(tx, client, event, kind, *args):
            original(tx, client, event, kind, *args)
            if kind == "LISTING_CLOSED":
                raise RuntimeError("simulated write failure")
        self.candidate("other")
        with patch.object(repo, "_proposal_notice", side_effect=fail):
            with self.assertRaises(RuntimeError):
                self.resolve(proposal)
        self.assertEqual(self.col("PROPOSALS").document(proposal["id"]).get().to_dict()["status"], "PENDING")
        self.assertEqual(repo.listing_availability(repo.get_listing("home")), "ACTIVE")
        self.assertEqual(self.col("SELECTIONS").document("home").get().to_dict()["pending_proposal_id"], proposal["id"])
        self.resolve(proposal)
        self.assertEqual(len([s for s in self.col("NOTIFICATIONS").stream() if s.to_dict()["type"] == "LISTING_CLOSED"]), 1)

    def test_http_creation_resolution_codes_and_mutation_lock(self):
        data = {"listing_id": "home", "match_id": self.match, "request_id": "http"}
        response = self.request("post", "/api/propuestas", data=data)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(self.request("post", "/api/propuestas", data=data).status_code, 200)
        proposal_id = response.json()["id"]
        edit = {"title": "Changed", "street": "Street", "city": "Barcelona", "postal_code": "08001", "description": "Description", "price": "950.50", "surface": "65.50", "bedrooms": 2, "bathrooms": 1, "people": 3, "shared_accommodation": "No"}
        self.assertEqual(self.request("patch", "/api/inmuebles/home", data=edit).status_code, 409)
        self.assertEqual(self.request("put", "/api/inmuebles/home/disponibilidad", data={"availability": "PAUSED"}).status_code, 409)
        path = "/api/propuestas/" + proposal_id + "/rechazar"
        self.assertEqual(self.request("post", path, "buyer", {}).status_code, 200)
        self.assertEqual(self.request("post", path, "buyer", {}).status_code, 200)
        self.assertEqual(self.request("patch", "/api/inmuebles/home", data=edit).status_code, 200)
        self.assertEqual(self.request("put", "/api/inmuebles/home/disponibilidad", data={"availability": "PAUSED"}).status_code, 200)
        self.assertEqual(self.request("post", "/api/propuestas/" + proposal_id + "/aceptar", "buyer", {}).status_code, 409)


    def test_creation_notice_failure_and_same_key_race(self):
        with patch.object(repo, "_proposal_notice", side_effect=RuntimeError("failure")):
            with self.assertRaises(RuntimeError):
                self.create()
        self.assertEqual(list(self.col("PROPOSALS").stream()), [])
        self.assertEqual(list(self.col("PROPOSAL_REQUESTS").stream()), [])
        results = self.race(lambda: self.create(), lambda: self.create())
        self.assertEqual(sorted(r[1] for r in results), [False, True])
        self.assertEqual(len(list(self.col("PROPOSALS").stream())), 1)

    def test_history_pagination_and_notice_read_contract(self):
        for i in range(3):
            proposal, _ = self.create(str(i))
            self.resolve(proposal, "REJECTED")
        response = self.client.get("/api/propuestas?limit=2", HTTP_AUTHORIZATION="Bearer buyer")
        self.assertEqual(response.status_code, 200)
        first = response.json()
        next_page = self.client.get("/api/propuestas", {"limit": 2, "cursor": first["next_cursor"]}, HTTP_AUTHORIZATION="Bearer buyer")
        self.assertEqual(len(first["items"]), 2)
        self.assertEqual(len(next_page.json()["items"]), 1)
        self.assertEqual(len({r["id"] for r in first["items"] + next_page.json()["items"]}), 3)
        self.assertEqual(self.client.get("/api/propuestas", {"cursor": first["next_cursor"]}, HTTP_AUTHORIZATION="Bearer seller").status_code, 400)
        # New HTTP client/session still reads persistent proposals.
        fresh_client = Client(enforce_csrf_checks=True)
        self.assertEqual(len(fresh_client.get("/api/propuestas", HTTP_AUTHORIZATION="Bearer buyer").json()["items"]), 3)
        notices = fresh_client.get("/api/notificaciones", HTTP_AUTHORIZATION="Bearer buyer").json()["items"]
        self.assertEqual(len(notices), 3)
        self.assertTrue(all(n["listing"]["id"] == "home" for n in notices))

    def test_missing_recipient_profile_is_not_a_valid_candidate(self):
        self.col("USERS").document("buyer").delete()
        with self.assertRaises(repo.ProposalNotFound):
            self.create()

    def test_nonconfirmed_match_and_cross_listing_are_rejected(self):
        pending = self.candidate("pending")
        with self.assertRaises(repo.DecisionConflict):
            self.create(match=pending)
        self.col("LISTINGS").document("other-home").create(listing(seller_uid="seller"))
        with self.assertRaises(repo.ProposalNotFound):
            self.create(home="other-home")

    def test_matches_remain_visible_with_closed_availability(self):
        proposal, _ = self.create()
        self.resolve(proposal)
        for uid in ("buyer", "seller"):
            response = self.request("get", "/api/matches", uid)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["items"][0]["listing"]["availability"], "CLOSED")
            self.assertEqual(response.json()["items"][0]["status"], "CONFIRMED")


    def test_durable_batches_resume_after_partial_delivery_without_duplicates(self):
        self.candidate("other-one")
        self.candidate("other-two", confirm=True)
        proposal, _ = self.create()
        with patch.object(repo, "INLINE_CLOSURE_NOTICE_LIMIT", 1), patch.object(repo, "CLOSURE_EVENT_BATCH_SIZE", 1):
            with patch.object(repo, "process_selection_notifications", side_effect=RuntimeError("worker unavailable")):
                self.resolve(proposal)
        self.assertEqual(repo.listing_availability(repo.get_listing("home")), "CLOSED")
        self.assertEqual(len(list(self.col("SELECTION_EVENTS").stream())), 2)
        self.assertEqual(repo.process_selection_notifications(limit=1), 1)
        with patch.object(repo, "_proposal_notice", side_effect=RuntimeError("delivery failure")):
            with self.assertRaises(RuntimeError):
                repo.process_selection_notifications()
        self.assertEqual(len([s for s in self.col("NOTIFICATIONS").stream() if s.to_dict()["type"] == "LISTING_CLOSED"]), 1)
        self.assertEqual(repo.process_selection_notifications(), 1)
        self.assertEqual(repo.process_selection_notifications(), 0)
        notices = [s.to_dict() for s in self.col("NOTIFICATIONS").stream() if s.to_dict()["type"] == "LISTING_CLOSED"]
        self.assertEqual(len(notices), 2)
        self.assertEqual({n["recipient_uid"] for n in notices}, {"other-one", "other-two"})

    def test_event_persistence_failure_rolls_back_acceptance(self):
        self.candidate("other")
        proposal, _ = self.create()
        with patch.object(repo, "_closure_notices", side_effect=RuntimeError("event failure")):
            with self.assertRaises(RuntimeError):
                self.resolve(proposal)
        self.assertEqual(self.col("PROPOSALS").document(proposal["id"]).get().to_dict()["status"], "PENDING")
        self.assertEqual(repo.listing_availability(repo.get_listing("home")), "ACTIVE")


@skipUnless(os.environ.get("FIREBASE_AUTH_EMULATOR_HOST") and os.environ.get("FIRESTORE_EMULATOR_HOST"), "Requires both local emulators")
class ProposalRealAuthTests(SimpleTestCase):
    def test_logout_reauthentication_persistence_and_direct_client_denial(self):
        import time
        import requests
        from firebase_admin import initialize_app, delete_app
        for env in ("FIREBASE_AUTH_EMULATOR_HOST", "FIRESTORE_EMULATOR_HOST"):
            self.assertTrue(os.environ[env].startswith(("localhost:", "127.0.0.1:")))
        app = initialize_app(options={"projectId": "demo-swipehome-us4"}, name="us9-" + uuid4().hex)
        self.addCleanup(delete_app, app)
        db = firestore.Client(project="demo-swipehome-us4", credentials=AnonymousCredentials())
        self.addCleanup(db.close)
        prefix = uuid4().hex
        for name in ("LISTINGS", "SWIPES", "MATCHES", "NOTIFICATIONS", "PROPOSALS", "SELECTIONS", "PROPOSAL_REQUESTS", "SELECTION_EVENTS", "USERS"):
            self.enterContext(patch.object(repo, name + "_COLLECTION", prefix + name))
        self.enterContext(patch("accounts.repository.get_app", return_value=app))
        self.enterContext(patch("accounts.authentication.get_app", return_value=app))
        self.enterContext(patch("accounts.repository.firestore.client", return_value=db))
        password = "Test password 123456!"
        accounts = {}
        for role in ("SELLER", "BUYER"):
            user = auth.create_user(email=role.lower() + prefix + "@example.com", password=password, display_name=role, app=app)
            self.addCleanup(auth.delete_user, user.uid, app=app)
            repo.create_user_profile(user.uid, name=role, email=user.email, role=role)
            accounts[role] = user
        def login(role):
            response = requests.post("http://" + os.environ["FIREBASE_AUTH_EMULATOR_HOST"] + "/identitytoolkit.googleapis.com/v1/accounts:signInWithPassword",
                params={"key": "demo-key"}, json={"email": accounts[role].email, "password": password, "returnSecureToken": True}, timeout=10)
            self.assertEqual(response.status_code, 200)
            return response.json()["idToken"]
        buyer, seller = accounts["BUYER"].uid, accounts["SELLER"].uid
        db.collection(repo.LISTINGS_COLLECTION).document("home").create(listing(seller_uid=seller))
        _, match, _ = repo.record_decision(buyer, "home", "LIKE", buyer_name="BUYER")
        repo.record_seller_decision(seller, match["id"], "LIKE")
        token = login("SELLER")
        client = Client(enforce_csrf_checks=True)
        response = client.post("/api/propuestas", json.dumps({"listing_id": "home", "match_id": match["id"], "request_id": "real-auth"}), content_type="application/json", HTTP_AUTHORIZATION="Bearer " + token)
        self.assertEqual(response.status_code, 201, response.content)
        proposal_id = response.json()["id"]
        token = login("BUYER")
        headers = {"HTTP_AUTHORIZATION": "Bearer " + token}
        self.assertEqual(client.get("/api/propuestas/" + proposal_id, **headers).status_code, 200)
        self.assertEqual(client.post("/api/auth/logout", **headers).status_code, 204)
        self.assertEqual(client.get("/api/propuestas/" + proposal_id, **headers).status_code, 401)
        time.sleep(1.05)
        token = login("BUYER")
        response = Client().get("/api/propuestas/" + proposal_id, HTTP_AUTHORIZATION="Bearer " + token)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "PENDING")
        # Even an authenticated client cannot bypass the Admin-only backend.
        base = "http://" + os.environ["FIRESTORE_EMULATOR_HOST"] + "/v1/projects/demo-swipehome-us4/databases/(default)/documents/"
        for collection, identifier in ((repo.PROPOSALS_COLLECTION, proposal_id), (repo.SELECTIONS_COLLECTION, "home"),
                                       (repo.LISTINGS_COLLECTION, "home"), (repo.MATCHES_COLLECTION, match["id"]),
                                       (repo.SWIPES_COLLECTION, match["id"])):
            url = base + collection + "/" + identifier
            for method in (requests.get, requests.patch):
                response = method(url, headers={"Authorization": "Bearer " + token}, timeout=10)
                self.assertEqual(response.status_code, 403, response.text)
