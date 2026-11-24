"""US9.7: HTTP real en loopback, tokens Auth y persistencia Firestore demo."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch
from uuid import uuid4

from google.api_core.exceptions import ServiceUnavailable
from google.cloud.firestore_v1.transaction import Transaction

from accounts import repository
from properties.test_discovery import listing
from qa.fixtures import EmulatorFixture


class SelectionIntegrationTests(EmulatorFixture):
    def race(self, repository_method, *requests_to_start):
        original = getattr(repository, repository_method)
        barrier = Barrier(len(requests_to_start), timeout=15)

        def enter_together(*args, **kwargs):
            barrier.wait()
            return original(*args, **kwargs)

        with patch.object(repository, repository_method, side_effect=enter_together):
            with ThreadPoolExecutor(max_workers=len(requests_to_start)) as pool:
                responses = [pool.submit(request) for request in requests_to_start]
                return [response.result(timeout=80) for response in responses]


    def test_proposal_requires_a_confirmed_match_for_that_home(self):
        self.seed("other-home", "other_seller")
        self.candidate("buyer", "PENDING")
        self.candidate("other", "REJECT")
        self.candidate("declined", "PASS")
        self.candidate("outsider", identifier="other-home", seller="other_seller")
        before = self.snapshot()
        for user, expected in (("buyer", 409), ("other", 409), ("pending", 404), ("declined", 404), ("outsider", 404)):
            with self.subTest(user=user):
                self.assert_status(self.propose(user), expected)
        self.assertEqual(self.snapshot(), before)

        self.seed("same-seller", "seller")
        decision_id = self.candidate("buyer", identifier="same-seller")
        proposal = self.assert_status(self.propose(identifier="same-seller"), 201)
        self.assertEqual((proposal["status"], proposal["match_id"]), ("PENDING", decision_id))
        self.assertEqual(self.rows("selections")["same-seller"]["pending_proposal_id"], proposal["id"])
        self.assertEqual(self.rows("listings")["home"], before["listings"]["home"])

    def test_only_the_owner_and_recipient_can_access_or_update_the_proposal(self):
        self.candidate("buyer")
        self.candidate("other")
        proposal = self.assert_status(self.propose(), 201)
        proposal_id = proposal["id"]
        detail_url = f"/api/propuestas/{proposal_id}"
        before = self.snapshot()

        self.assert_status(self.request("GET", detail_url), 401)
        self.assert_status(self.request("GET", detail_url, token="invalid"), 401)
        self.assert_status(self.propose(seller="buyer"), 403)
        self.assert_status(self.propose(seller="other_seller"), 404)
        for user in ("other", "outsider", "other_seller"):
            with self.subTest(user=user):
                self.assert_status(self.request("GET", detail_url, user), 404)
                self.assertEqual(self.assert_status(self.request("GET", "/api/propuestas", user), 200)["items"], [])
        self.assert_status(self.decide(proposal_id, "ACCEPT", "other"), 404)
        self.assert_status(self.decide(proposal_id, "REJECT", "outsider"), 404)
        self.assert_status(self.decide(proposal_id, "CANCEL", "other_seller"), 404)
        self.assert_status(self.decide(proposal_id, "ACCEPT", "seller"), 403)
        self.assert_status(self.decide(proposal_id, "REJECT", "seller"), 403)
        self.assert_status(self.decide(proposal_id, "CANCEL"), 403)
        self.assert_status(self.request("GET", "/api/propuestas", "other", params={"uid": self.uids["buyer"]}), 400)
        self.assert_status(self.request("POST", detail_url + "/aceptar", body={"decision": "ACCEPT"}), 401)
        self.assert_status(self.request(
            "POST", detail_url + "/aceptar", "other", body={"uid": self.uids["buyer"]},
        ), 400)
        self.assert_status(self.request(
            "POST", "/api/propuestas", "seller",
            body={"listing_id": "home", "match_id": "../invalid", "request_id": "intent"},
        ), 400)
        self.assertEqual(self.snapshot(), before)

        for user in ("buyer", "seller"):
            detail = self.assert_status(self.request("GET", detail_url, user), 200)
            self.assertEqual(detail["seller"], {"id": self.uids["seller"], "name": "Cuenta seller"})
            self.assertEqual(detail["listing"]["price"], "950.50")
            self.assertEqual(detail["listing"]["surface"], "65.50")
            self.assertEqual(detail["listing"]["description"], listing()["description"])
            self.assertEqual(detail["listing"]["photos"], listing()["photos"])
            self.assertEqual(detail["listing"]["people"], 3)
            self.assertIs(detail["listing"]["shared_accommodation"], False)
            self.assertEqual(detail["listing"]["availability"], "ACTIVE")
            items = self.assert_status(self.request("GET", "/api/propuestas", user), 200)["items"]
            self.assertEqual(items, [proposal])

    def test_acceptance_closes_only_its_home_and_notifies_affected_candidates_privately(self):
        self.seed("another", "other_seller")
        self.seed("open", "seller")
        self.candidate("buyer")
        self.candidate("other")
        self.candidate("declined", "REJECT")
        self.candidate("pending", "PENDING", identifier="open")
        self.candidate("pending", "PENDING")
        self.candidate("other", identifier="another", seller="other_seller")
        unrelated = self.assert_status(self.propose("other", seller="other_seller", identifier="another"), 201)
        proposal = self.assert_status(self.propose(), 201)
        proposal_id = proposal["id"]
        before = self.snapshot()
        def explore():
            result = self.assert_status(self.request("GET", "/api/inmuebles/explorar", "outsider"), 200)
            return {row["id"] for row in result["items"]}

        self.assertEqual(explore(), {"home", "another", "open"})
        accepted = self.assert_status(self.decide(proposal_id, "ACCEPT"), 200)
        self.assertEqual(accepted["status"], "ACCEPTED")
        after = self.snapshot()
        selected = after["listings"]["home"]
        self.assertEqual(repository.listing_availability(selected), "CLOSED")
        self.assertEqual(after["proposals"][proposal_id]["buyer_uid"], self.uids["buyer"])
        self.assertEqual(after["selections"]["home"]["accepted_proposal_id"], proposal_id)
        self.assertEqual(selected["closed_at"], after["proposals"][proposal_id]["resolved_at"])
        self.assertIsNone(after["selections"]["home"].get("pending_proposal_id"))
        self.assertEqual(explore(), {"another", "open"})
        self.assertEqual(after["proposals"][unrelated["id"]], before["proposals"][unrelated["id"]])
        for name in ("another", "open"):
            self.assertEqual(after["listings"][name], before["listings"][name])
        for collection in ("swipes", "matches"):
            self.assertEqual(after[collection], before[collection])

        candidates = self.assert_status(
            self.request("GET", "/api/candidatos", "seller", params={"limit": 1}), 200,
        )
        with self.subTest("las candidaturas de una vivienda cerrada no ocupan la primera página"):
            self.assertEqual([row["listing"]["id"] for row in candidates["items"]], ["open"])
            self.assertIsNone(candidates["next_cursor"])
        for user in ("buyer", "other", "seller"):
            matches = self.assert_status(self.request("GET", "/api/matches", user), 200)["items"]
            for item in matches:
                self.assertEqual(item["listing"]["availability"], "CLOSED" if item["listing"]["id"] == "home" else "ACTIVE")
        self.assertNotIn(self.uids["buyer"], self.request("GET", "/api/matches", "other").text)
        self.assertEqual(
            [row["type"] for row in self.notices("buyer")], ["PROPOSAL"],
        )
        self.assertEqual([row["type"] for row in self.notices("seller")], ["ACCEPTED"])
        for user in ("other", "pending"):
            unavailable = [row for row in self.notices(user) if row["type"] == "LISTING_CLOSED"]
            self.assertEqual(len(unavailable), 1)
            notice = unavailable[0]
            self.assertNotIn("proposal_id", notice)
            self.assertEqual(notice["listing"]["id"], "home")
            self.assertNotIn(proposal_id, notice["id"])
            for persisted in after["notifications"].values():
                if persisted["recipient_uid"] == self.uids[user] and persisted["type"] == "LISTING_CLOSED":
                    self.assertEqual(set(persisted), set(notice) - {"id", "listing"} | {
                        "recipient_uid", "listing_id", "listing_title",
                    })
        self.assertEqual(self.notices("declined"), [])
        self.assertEqual(self.notices("outsider"), [])
        self.assert_status(self.propose("other"), 409)
        self.assertEqual(self.snapshot(), after)

    def test_reject_cancel_and_delayed_retries_keep_separate_intents_and_notices(self):
        confirmed = self.candidate("buyer")
        self.candidate("other")
        initial = self.rows("listings")["home"]
        key = uuid4().hex
        first = self.assert_status(self.propose(key=key), 201)
        first_id = first["id"]
        self.assertEqual(self.assert_status(self.propose(key=key), 200), first)
        self.assert_status(self.propose("other", key=key), 409)
        rejected = self.assert_status(self.decide(first_id, "REJECT"), 200)
        self.assertEqual(rejected["status"], "REJECTED")
        self.assertEqual(self.rows("listings")["home"], initial)

        second = self.assert_status(self.propose(), 201)
        second_id = second["id"]
        self.assertNotEqual(second_id, first_id)
        self.assertEqual(second["match_id"], confirmed)
        self.assertEqual(self.assert_status(self.propose(key=key), 200), rejected)
        self.assertEqual(self.assert_status(self.decide(first_id, "REJECT"), 200), rejected)
        self.assert_status(self.decide(first_id, "ACCEPT"), 409)
        self.assertEqual(self.rows("selections")["home"]["pending_proposal_id"], second_id)
        cancelled = self.assert_status(self.decide(second_id, "CANCEL", "seller"), 200)
        self.assertEqual(cancelled["status"], "CANCELLED")
        self.assertEqual(self.assert_status(self.decide(second_id, "CANCEL", "seller"), 200), cancelled)
        self.assertEqual(self.rows("listings")["home"], initial)
        third = self.assert_status(self.propose("other"), 201)

        self.assertEqual(
            {key: row["status"] for key, row in self.rows("proposals").items()},
            {first_id: "REJECTED", second_id: "CANCELLED", third["id"]: "PENDING"},
        )
        self.assertCountEqual(
            [notice["type"] for notice in self.notices("buyer")],
            ["PROPOSAL", "PROPOSAL", "CANCELLED"],
        )
        self.assertEqual([row["type"] for row in self.notices("seller")], [
            "REJECTED",
        ])
        page = self.assert_status(self.request("GET", "/api/propuestas", "buyer", params={"limit": 1}), 200)
        self.assertEqual(page["items"], [cancelled])
        params = {"limit": 1, "cursor": page["next_cursor"]}
        self.assertEqual(
            self.assert_status(self.request("GET", "/api/propuestas", params=params, token=self.login("buyer")), 200),
            {"items": [rejected], "next_cursor": None},
        )
        self.assert_status(self.request("GET", "/api/propuestas", "other", params=params), 400)

    def test_concurrent_incompatible_proposals_and_repeated_acceptance_have_one_winner(self):
        self.candidate("buyer")
        self.candidate("other")
        expected_matches = self.rows("matches")
        expected_swipes = self.rows("swipes")
        responses = self.race("create_proposal", lambda: self.propose("buyer"), lambda: self.propose("other"))
        self.assertCountEqual([response.status_code for response in responses], [201, 409])
        proposal = next(response.json() for response in responses if response.status_code == 201)
        winner = next(user for user in ("buyer", "other") if self.uids[user] == self.rows("proposals")[proposal["id"]]["buyer_uid"])
        proposal_id = proposal["id"]
        self.assertEqual(set(self.rows("proposals")), {proposal_id})
        self.assertEqual(self.rows("selections")["home"]["pending_proposal_id"], proposal_id)
        self.assertEqual(len(self.notices(winner)), 1)

        def accept():
            return self.decide(proposal_id, "ACCEPT", winner)

        responses = self.race("resolve_proposal", accept, accept)
        self.assertCountEqual([response.status_code for response in responses], [200, 200])
        self.assertEqual(responses[0].json(), responses[1].json())
        self.assertEqual(self.rows("proposals")[proposal_id]["status"], "ACCEPTED")
        self.assertEqual(self.rows("selections")["home"]["accepted_proposal_id"], proposal_id)
        self.assertEqual(self.rows("proposals")[proposal_id]["buyer_uid"], self.uids[winner])
        self.assertEqual(self.rows("matches"), expected_matches)
        self.assertEqual(self.rows("swipes"), expected_swipes)
        events = [row["type"] for row in self.rows("notifications").values() if row["type"] != "INTEREST"]
        self.assertCountEqual(events, ["PROPOSAL", "ACCEPTED", "LISTING_CLOSED"])

    def test_concurrent_accept_and_cancel_leave_one_atomic_terminal_state(self):
        self.candidate("buyer")
        proposal_id = self.assert_status(self.propose(), 201)["id"]
        responses = self.race(
            "resolve_proposal",
            lambda: self.decide(proposal_id, "ACCEPT"),
            lambda: self.decide(proposal_id, "CANCEL", "seller"),
        )
        self.assertCountEqual([response.status_code for response in responses], [200, 409])
        winner = next(response.json()["status"] for response in responses if response.status_code == 200)
        selection = self.rows("proposals")[proposal_id]
        home = self.rows("listings")["home"]
        self.assertEqual(selection["status"], winner)
        self.assertIsNone(self.rows("selections")["home"].get("pending_proposal_id"))
        self.assertEqual(repository.listing_availability(home), "ACTIVE" if winner == "CANCELLED" else "CLOSED")
        self.assertEqual(self.rows("selections")["home"].get("accepted_proposal_id"), proposal_id if winner == "ACCEPTED" else None)
        self.assertEqual([row["type"] for row in self.notices("buyer")], [
            *(["CANCELLED"] if winner == "CANCELLED" else []), "PROPOSAL",
        ])
        self.assertEqual([row["type"] for row in self.notices("seller")], (
            ["ACCEPTED"] if winner == "ACCEPTED" else []
        ))

    def test_firestore_rejects_commits_without_partial_proposals_or_closures(self):
        self.candidate("buyer")
        before = self.snapshot()
        key = uuid4().hex
        real_commit = Transaction._commit
        absent = self.collections["listings"].document("inexistente")

        def commit_with_failed_precondition(transaction):
            transaction.update(absent, {"published": False})
            return real_commit(transaction)

        with patch.object(Transaction, "_commit", commit_with_failed_precondition):
            self.assert_status(self.propose(key=key), 500)
        self.assertEqual(self.snapshot(), before)
        proposal = self.assert_status(self.propose(key=key), 201)
        self.assertEqual(self.rows("selections")["home"]["pending_proposal_id"], proposal["id"])
        self.assertEqual([row["type"] for row in self.notices("buyer")], [
            "PROPOSAL",
        ])
        pending = self.snapshot()
        with patch.object(Transaction, "_commit", commit_with_failed_precondition):
            self.assert_status(self.decide(proposal["id"], "ACCEPT"), 500)
        self.assertEqual(self.snapshot(), pending)
        self.assert_status(self.decide(proposal["id"], "ACCEPT"), 200)
        self.assertEqual(self.rows("proposals")[proposal["id"]]["status"], "ACCEPTED")
        self.assertEqual(repository.listing_availability(self.rows("listings")["home"]), "CLOSED")

    def test_notification_failure_rolls_back_acceptance_and_retry_writes_each_notice_once(self):
        self.candidate("buyer")
        self.candidate("other")
        proposal_id = self.assert_status(self.propose(), 201)["id"]
        before = self.snapshot()

        def fail_unavailable(transaction, client, listing_id, title, recipients):
            self.assertEqual(recipients, {self.uids["other"]})
            raise ServiceUnavailable("Fallo controlado al preparar el aviso")

        with patch.object(repository, "_closure_notices", side_effect=fail_unavailable) as send:
            self.assert_status(self.decide(proposal_id, "ACCEPT"), 500)
            send.assert_called_once()
        self.assertEqual(self.snapshot(), before)
        accepted = self.assert_status(self.decide(proposal_id, "ACCEPT"), 200)
        after = self.snapshot()
        self.assertEqual(self.assert_status(self.decide(proposal_id, "ACCEPT"), 200), accepted)
        self.assertEqual(self.snapshot(), after)
        self.assertEqual(repository.listing_availability(after["listings"]["home"]), "CLOSED")
        self.assertEqual(after["proposals"][proposal_id]["status"], "ACCEPTED")
        self.assertEqual([row["type"] for row in self.notices("other")], ["LISTING_CLOSED"])
        self.assertEqual([row["type"] for row in self.notices("seller")], ["ACCEPTED"])

    def test_response_loss_after_real_commit_is_recoverable_for_creation_and_acceptance(self):
        self.candidate("buyer")
        real_commit = Transaction._commit

        def lose_response(transaction):
            real_commit(transaction)
            raise ServiceUnavailable("Respuesta perdida después del commit")

        key = uuid4().hex
        with patch.object(Transaction, "_commit", lose_response):
            self.assert_status(self.propose(key=key), 500)
        persisted = self.snapshot()
        self.assertEqual(len(persisted["proposals"]), 1)
        proposal_id, proposal = next(iter(persisted["proposals"].items()))
        self.assertEqual(proposal["status"], "PENDING")
        self.assertEqual(persisted["selections"]["home"]["pending_proposal_id"], proposal_id)
        self.assertEqual(self.assert_status(self.propose(key=key), 200)["id"], proposal_id)
        self.assertEqual(self.snapshot(), persisted)

        with patch.object(Transaction, "_commit", lose_response):
            self.assert_status(self.decide(proposal_id, "ACCEPT"), 500)
        persisted = self.snapshot()
        self.assertEqual(persisted["proposals"][proposal_id]["status"], "ACCEPTED")
        self.assertEqual(persisted["selections"]["home"]["accepted_proposal_id"], proposal_id)
        self.assertEqual(self.assert_status(self.decide(proposal_id, "ACCEPT"), 200)["status"], "ACCEPTED")
        self.assertEqual(self.assert_status(self.propose(key=key), 200)["status"], "ACCEPTED")
        self.assertEqual(self.snapshot(), persisted)
        self.assertEqual([row["type"] for row in self.notices("buyer")], ["PROPOSAL"])
        self.assertEqual(len(self.notices("seller")), 1)
