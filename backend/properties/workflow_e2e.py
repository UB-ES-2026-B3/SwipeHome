"""E2E de candidaturas, filtros y propuestas simultáneas en dos viviendas."""
from datetime import timedelta

from accounts import repository
from properties.test_discovery import STAMP
from qa.fixtures import BrowserFixture


class WorkflowBrowserTests(BrowserFixture):
    def test_interest_confirmation_and_rejection(self):
        accepted, _ = self.publish(title="Piso para confirmar")
        rejected, _ = self.publish(title="Piso para rechazar")
        self.browser("workflows", "matches")
        accepted_key = repository.decision_key(self.uids["buyer"], accepted)
        rejected_key = repository.decision_key(self.uids["other"], rejected)
        self.assertEqual(self.rows("matches")[accepted_key]["status"], "CONFIRMED")
        self.assertEqual(self.rows("matches")[rejected_key]["status"], "REJECTED")
        self.assertEqual(set(self.rows("matches")), {accepted_key, rejected_key})
        self.assertEqual(len(self.rows("notifications")), 2)

    def test_preferences_profile_explorer_and_private_reset(self):
        self.seed("affordable", "seller", title="Piso asequible", price_cents=45000)
        self.seed("discarded", "seller", title="Piso descartado", created_at=STAMP + timedelta(seconds=1))
        self.browser("workflows", "preferences")
        key = repository.decision_key(self.uids["buyer"], "discarded")
        self.assertEqual({key: "PASS"}, {doc: row["value"] for doc, row in self.rows("swipes").items()})
        self.assertTrue(all(value is None for value in repository.get_search_preferences(self.uids["buyer"]).values()))
        self.assertTrue(all(value is None for value in repository.get_search_preferences(self.uids["other"]).values()))

    def test_two_homes_keep_independent_proposal_status(self):
        self.seed("second", "seller", title="Piso todavía disponible")
        self.candidate("buyer")
        self.candidate("other")
        self.candidate("other", identifier="second")
        matches = self.rows("matches")
        self.browser("workflows", "independent-proposals")
        proposals = {record["listing_id"]: record for record in self.rows("proposals").values()}
        self.assertEqual(proposals["home"]["status"], "ACCEPTED")
        self.assertEqual(proposals["second"]["status"], "REJECTED")
        homes = self.rows("listings")
        self.assertEqual(repository.listing_availability(homes["home"]), "CLOSED")
        self.assertEqual(repository.listing_availability(homes["second"]), "ACTIVE")
        self.assertIsNone(self.rows("selections")["second"].get("pending_proposal_id"))
        self.assertEqual(matches, self.rows("matches"))
