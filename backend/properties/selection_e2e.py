"""Recorridos Chromium, Vite, Django y emuladores. Invocación explícita."""
import json
from collections import Counter
from unittest.mock import patch

from firebase_admin import auth

from accounts import repository
from qa.fixtures import BrowserFixture


class SelectionBrowserTests(BrowserFixture):

    def setUp(self):
        super().setUp()
        self.home = self.collections["listings"].document("home")
        self.candidate("buyer")
        self.candidate("other")
        self.swipes_before = self.rows("swipes")
        self.matches_before = self.rows("matches")

    def run_browser(self, scenario):
        self.browser("selection", scenario)
        self.assertEqual(self.rows("swipes"), self.swipes_before)
        self.assertEqual(self.rows("matches"), self.matches_before)

    def assert_notices(self, expected):
        events = [
            (row["type"], row["recipient_uid"])
            for row in self.rows("notifications").values() if row["type"] != "INTEREST"
        ]
        self.assertEqual(Counter(events), Counter((event, self.uids[person]) for event, person in expected))

    def assert_accepted(self):
        records = self.rows("proposals")
        self.assertEqual(len(records), 1)
        selection_id, record = next(iter(records.items()))
        self.assertEqual(record["status"], "ACCEPTED")
        home = self.home.get().to_dict()
        self.assertEqual(self.rows("selections")["home"]["accepted_proposal_id"], selection_id)
        self.assertEqual(self.rows("selections")["home"]["selected_buyer_uid"], self.uids["buyer"])
        self.assertEqual(repository.listing_availability(home), "CLOSED")
        self.assertIsNone(self.rows("selections")["home"]["pending_proposal_id"])

    def assert_open_with_new_proposal(self, state, new_buyer):
        records = self.rows("proposals")
        self.assertCountEqual([record["status"] for record in records.values()], [state, "PENDING"])
        home = self.home.get().to_dict()
        self.assertIs(home["published"], True)
        self.assertNotIn("accepted_proposal_id", self.rows("selections")["home"])
        self.assertEqual(records[self.rows("selections")["home"]["pending_proposal_id"]]["buyer_uid"], self.uids[new_buyer])

    def test_acceptance_availability_privacy_and_new_session(self):
        self.candidate("pending", "PENDING")
        self.swipes_before = self.rows("swipes")
        self.matches_before = self.rows("matches")
        app = repository.get_app()
        original = repository.create_proposal

        def update_terms_after_send(*args, **kwargs):
            record, created = original(*args, **kwargs)
            if created:
                self.home.update({"price_cents": 99999, "description": "Condiciones actualizadas"})
                auth.update_user(self.uids["seller"], display_name="Cuenta seller actualizada", app=app)
            return record, created

        self.addCleanup(auth.update_user, self.uids["seller"], display_name="Cuenta seller", app=app)
        with patch.object(repository, "create_proposal", side_effect=update_terms_after_send):
            self.run_browser("acceptance")
        self.assert_accepted()
        self.assert_notices([
            ("PROPOSAL", "buyer"), ("ACCEPTED", "seller"),
            ("LISTING_CLOSED", "other"), ("LISTING_CLOSED", "pending"),
        ])
        for row in self.rows("notifications").values():
            if row["type"] == "LISTING_CLOSED":
                self.assertNotIn("selection_id", row)
                self.assertNotIn(self.uids["buyer"], json.dumps(row, default=str))

    def test_rejection_keeps_home_open_and_allows_another_buyer(self):
        self.run_browser("rejection")
        self.assert_open_with_new_proposal("REJECTED", "other")
        self.assert_notices([("PROPOSAL", "buyer"), ("REJECTED", "seller"), ("PROPOSAL", "other")])

    def test_cancellation_invalidates_stale_buyer_and_allows_another_proposal(self):
        self.run_browser("cancellation")
        self.assert_open_with_new_proposal("CANCELLED", "buyer")
        self.assert_notices([("PROPOSAL", "buyer"), ("CANCELLED", "buyer"), ("PROPOSAL", "buyer")])

    def test_browser_retries_network_failure_and_committed_responses_without_duplicates(self):
        self.run_browser("errors")
        self.assert_accepted()
        self.assert_notices([
            ("PROPOSAL", "buyer"), ("ACCEPTED", "seller"), ("LISTING_CLOSED", "other"),
        ])
