"""Recorridos Chromium, Vite, Django y emuladores. Invocación explícita."""
import json
import os
import subprocess
from collections import Counter
from pathlib import Path
from unittest.mock import patch

from firebase_admin import auth

from accounts import repository
from properties.test_selection import AUTH_HOST, FIRESTORE_HOST, PASSWORD, PROJECT, SelectionEmulatorFixture

FRONTEND = Path(__file__).resolve().parents[2] / "frontend"
LOCAL_PHOTO = "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7"


class SelectionBrowserTests(SelectionEmulatorFixture):
    @classmethod
    def setUpClass(cls):
        if (AUTH_HOST, FIRESTORE_HOST, os.environ.get("GCLOUD_PROJECT")) != (
            "127.0.0.1:9099", "127.0.0.1:8080", PROJECT,
        ):
            raise RuntimeError("La prueba exige el proyecto demo y los emuladores en loopback.")
        chrome = os.environ.get("SWIPEHOME_E2E_CHROME")
        if not chrome or not Path(chrome).resolve().is_file():
            raise RuntimeError("Define SWIPEHOME_E2E_CHROME con la ruta del ejecutable Chromium o Chrome.")
        cls.chrome = str(Path(chrome).resolve())
        super().setUpClass()

    def setUp(self):
        super().setUp()
        self.home = self.collections["listings"].document("home")
        self.home.update({"photos": [LOCAL_PHOTO]})
        self.candidate("buyer")
        self.candidate("other")
        self.swipes_before = self.rows("swipes")
        self.matches_before = self.rows("matches")

    def run_browser(self, scenario):
        env = {
            key: value for key, value in os.environ.items()
            if key not in {"FIREBASE_TOKEN", "FIREBASE_SERVICE_ACCOUNT_JSON", "GOOGLE_APPLICATION_CREDENTIALS"}
            and not key.startswith("VITE_")
        }
        result = subprocess.run(
            ["node", "e2e/selection.mjs"],
            input=json.dumps({
                "scenario": scenario, "backend": self.live_server_url, "authHost": AUTH_HOST,
                "chrome": self.chrome, "emails": self.emails, "password": PASSWORD,
            }),
            cwd=FRONTEND, env=env, capture_output=True, encoding="utf-8", timeout=150,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        print(result.stdout, end="", flush=True)
        self.assertEqual(self.rows("swipes"), self.swipes_before)
        self.assertEqual(self.rows("matches"), self.matches_before)

    def assert_notices(self, expected):
        events = [
            (row["type"].removeprefix("SELECTION_"), row["recipient_uid"])
            for row in self.rows("notifications").values() if row["type"].startswith("SELECTION_")
        ]
        self.assertEqual(Counter(events), Counter((event, self.uids[person]) for event, person in expected))

    def assert_accepted(self):
        records = self.rows("selections")
        self.assertEqual(len(records), 1)
        selection_id, record = next(iter(records.items()))
        self.assertEqual(record["status"], "ACCEPTED")
        home = self.home.get().to_dict()
        self.assertEqual(home["selected_selection_id"], selection_id)
        self.assertEqual(home["selected_buyer_uid"], self.uids["buyer"])
        self.assertIs(home["published"], False)
        self.assertIs(home["available"], False)
        self.assertNotIn("pending_selection_id", home)

    def assert_open_with_new_proposal(self, state, new_buyer):
        records = self.rows("selections")
        self.assertCountEqual([record["status"] for record in records.values()], [state, "PENDING"])
        home = self.home.get().to_dict()
        self.assertIs(home["published"], True)
        self.assertNotIn("selected_selection_id", home)
        self.assertEqual(records[home["pending_selection_id"]]["buyer_uid"], self.uids[new_buyer])

    def test_acceptance_availability_privacy_and_new_session(self):
        self.candidate("pending", "PENDING")
        self.swipes_before = self.rows("swipes")
        app = repository.get_app()
        original = repository.create_selection

        def update_terms_after_send(*args):
            record, created = original(*args)
            if created:
                self.home.update({"price_cents": 99999, "description": "Condiciones actualizadas"})
                auth.update_user(self.uids["seller"], display_name="Cuenta seller actualizada", app=app)
            return record, created

        self.addCleanup(auth.update_user, self.uids["seller"], display_name="Cuenta seller", app=app)
        with patch.object(repository, "create_selection", side_effect=update_terms_after_send):
            self.run_browser("acceptance")
        self.assert_accepted()
        self.assert_notices([
            ("PROPOSAL", "buyer"), ("ACCEPTED", "seller"), ("ACCEPTED", "buyer"),
            ("UNAVAILABLE", "other"), ("UNAVAILABLE", "pending"),
        ])
        for row in self.rows("notifications").values():
            if row["type"] == "SELECTION_UNAVAILABLE":
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
            ("PROPOSAL", "buyer"), ("ACCEPTED", "seller"), ("ACCEPTED", "buyer"), ("UNAVAILABLE", "other"),
        ])
