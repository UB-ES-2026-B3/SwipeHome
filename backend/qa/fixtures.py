"""Usuarios, colecciones aisladas, HTTP y navegador para los escenarios locales."""
import json
import os
import subprocess
from pathlib import Path
from unittest import skipUnless
from unittest.mock import patch
from uuid import uuid4

import requests
from django.test import LiveServerTestCase, tag
from firebase_admin import auth, delete_app

from accounts import repository
from properties.test_discovery import listing
from qa.environment import AUTH_HOST, HOST, PROJECT, blob_container, new_firebase

FRONTEND = Path(__file__).resolve().parents[2] / "frontend"
ROLES = {
    "seller": "SELLER", "other_seller": "SELLER", "buyer": "BUYER",
    "other": "BUYER", "pending": "BUYER", "declined": "BUYER", "outsider": "BUYER",
}
PASSWORD = "Test password value 123!"
LOCAL_PHOTO = "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7"


def remove_documents(collection):
    for snapshot in collection.stream(timeout=8):
        snapshot.reference.delete(retry=None, timeout=8)


def scoped_collections(test, db, names, *, class_scope=False):
    prefix = "qa_" + uuid4().hex
    enter = test.enterClassContext if class_scope else test.enterContext
    cleanup = test.addClassCleanup if class_scope else test.addCleanup
    collections = {}
    for name in names:
        collection = f"{prefix}_{name}"
        enter(patch.object(repository, f"{name.upper()}_COLLECTION", collection))
        collections[name] = db.collection(collection)
        cleanup(remove_documents, collections[name])
    return collections


@skipUnless(os.environ.get("FIREBASE_AUTH_EMULATOR_HOST") and os.environ.get("FIRESTORE_EMULATOR_HOST"),
            "Requiere emuladores locales.")
@tag("integration")
class EmulatorFixture(LiveServerTestCase):
    host = HOST
    databases = set()

    @classmethod
    def setUpClass(cls):
        app, cls.db = new_firebase()
        cls.addClassCleanup(delete_app, app)
        cls.addClassCleanup(cls.db.close)
        super().setUpClass()
        for target in ("accounts.repository.get_app", "accounts.authentication.get_app", "accounts.views.get_app"):
            cls.enterClassContext(patch(target, return_value=app))
        scoped_collections(cls, cls.db, ("users", "revocations"), class_scope=True)
        cls.uids, cls.emails, cls.tokens = {}, {}, {}
        suffix = uuid4().hex
        for user, role in ROLES.items():
            email = f"{user}-{suffix}@example.com"
            name = f"Cuenta {user}"
            account = auth.create_user(email=email, password=PASSWORD, display_name=name, app=app)
            cls.addClassCleanup(auth.delete_user, account.uid, app=app)
            cls.uids[user] = account.uid
            cls.emails[user] = email
            repository.create_user_profile(account.uid, name=name, email=email, role=role)
            cls.tokens[user] = cls.login(user)

    @classmethod
    def login(cls, user):
        with requests.Session() as session:
            session.trust_env = False
            response = session.post(
                f"http://{AUTH_HOST}/identitytoolkit.googleapis.com/v1/accounts:signInWithPassword",
                params={"key": "demo-key"},
                json={"email": cls.emails[user], "password": PASSWORD, "returnSecureToken": True},
                timeout=15,
            )
        response.raise_for_status()
        return response.json()["idToken"]

    def setUp(self):
        self.collections = scoped_collections(self, self.db, ("listings", "swipes", "matches", "selections", "notifications"))
        self.seed("home", "seller")

    def seed(self, identifier, seller, **attributes):
        fields = {**attributes, "seller_uid": self.uids[seller]}
        self.collections["listings"].document(identifier).create(listing(**fields))

    def request(self, method, url, user=None, *, body=None, params=None, token=None):
        if user is not None:
            token = self.tokens[user]
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        with requests.Session() as session:
            session.trust_env = False
            return session.request(
                method, self.live_server_url + url,
                headers=headers, json=body, params=params, timeout=75,
            )

    def assert_status(self, response, expected):
        self.assertEqual(response.status_code, expected, response.text)
        return response.json()

    def candidate(self, buyer, state="ACCEPT", *, identifier="home", seller="seller"):
        value = "PASS" if state == "PASS" else "LIKE"
        response = self.request("POST", f"/api/inmuebles/{identifier}/decision", buyer, body={"decision": value})
        decision_id = self.assert_status(response, 201)["decision"]["id"]
        if state in {"ACCEPT", "REJECT"}:
            response = self.request(
                "POST", f"/api/matches/candidaturas/{decision_id}/decision", seller,
                body={"decision": state},
            )
            self.assert_status(response, 201)
        return decision_id

    def propose(self, buyer="buyer", *, seller="seller", identifier="home", key=None):
        return self.request(
            "POST", f"/api/inmuebles/{identifier}/propuestas", seller,
            body={"buyer_uid": self.uids[buyer], "idempotency_key": key or uuid4().hex},
        )

    def decide(self, proposal_id, decision, user="buyer"):
        return self.request("POST", f"/api/propuestas/{proposal_id}/decision", user, body={"decision": decision})

    def notices(self, user):
        return [
            row for row in self.assert_status(self.request("GET", "/api/notificaciones", user), 200)["items"]
            if row["type"].startswith("SELECTION_")
        ]

    def rows(self, collection):
        return {doc.id: doc.to_dict() for doc in self.collections[collection].stream()}

    def snapshot(self):
        return {name: self.rows(name) for name in self.collections}

    def publish_response(self, *, user="seller", photos=None, **attributes):
        from properties.tests import VALID, jpeg

        stored_photos = photos or [jpeg()]
        container = blob_container()
        account_prefix = self.uids[user] + "/"
        previous = {blob.name for blob in container.list_blobs(name_starts_with=account_prefix)}

        def cleanup_blobs():
            for blob in container.list_blobs(name_starts_with=account_prefix):
                if blob.name not in previous:
                    container.delete_blob(blob.name)

        self.addCleanup(cleanup_blobs)
        with requests.Session() as session:
            session.trust_env = False
            return session.post(
                self.live_server_url + "/api/inmuebles",
                headers={"Authorization": "Bearer " + self.tokens[user]},
                data={**VALID, **attributes},
                files=[("photos", (photo.name, photo.read(), photo.content_type)) for photo in stored_photos],
                timeout=30,
            )

    def publish(self, **kwargs):
        listing_id = self.assert_status(self.publish_response(**kwargs), 201)["id"]
        return listing_id, self.rows("listings")[listing_id]


class BrowserFixture(EmulatorFixture):
    def seed(self, identifier, seller, **attributes):
        super().seed(identifier, seller, **{"photos": [LOCAL_PHOTO], **attributes})

    @classmethod
    def setUpClass(cls):
        chrome = os.environ.get("SWIPEHOME_E2E_CHROME")
        if not chrome or not Path(chrome).is_file():
            raise RuntimeError("Define SWIPEHOME_E2E_CHROME con la ruta del ejecutable Chrome/Chromium.")
        cls.chrome = str(Path(chrome).resolve())
        super().setUpClass()

    def browser(self, script, scenario, **configuration):
        env = {key: value for key, value in os.environ.items() if not key.startswith("VITE_")}
        result = subprocess.run(
            ["node", f"e2e/{script}.mjs"],
            input=json.dumps({
                "scenario": scenario, "backend": self.live_server_url, "authHost": AUTH_HOST,
                "chrome": self.chrome, "emails": self.emails, "password": PASSWORD,
                **configuration,
            }),
            cwd=FRONTEND, env=env, capture_output=True, encoding="utf-8", timeout=150, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        print(result.stdout, end="", flush=True)
