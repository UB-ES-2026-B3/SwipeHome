"""US11.7 sobre HTTP, Auth Emulator y Firestore Emulator."""
from concurrent.futures import ThreadPoolExecutor
import time
from threading import Barrier
from unittest.mock import patch
from uuid import uuid4

import requests
from google.cloud.firestore_v1.transaction import Transaction

from accounts import repository
from qa.environment import FIRESTORE_HOST, PROJECT
from qa.fixtures import EmulatorFixture, remove_documents, scoped_collections


class ConversationIntegrationTests(EmulatorFixture):
    def setUp(self):
        super().setUp()
        self.collections.update(scoped_collections(self, self.db, ("conversations",)))

    def assert_status(self, response, expected):
        self.assertIn("no-store", response.headers["Cache-Control"])
        return super().assert_status(response, expected)

    def open(self, match, user="buyer"):
        return self.request("POST", f"/api/matches/{match}/conversacion", user, body={})

    def prepare(self):
        match = super().candidate("buyer")
        data = self.assert_status(self.open(match), 201)
        messages = self.collections["conversations"].document(data["id"]).collection("messages")
        self.addCleanup(remove_documents, messages)
        return f"/api/conversaciones/{data['id']}"

    def send(self, url, content, key=None, user="buyer"):
        return self.request("POST", url + "/mensajes", user, body={
            "client_message_id": key or str(uuid4()), "content": content,
        })

    def race(self, method, *calls):
        start = Barrier(len(calls), timeout=15)
        original = getattr(repository, method)

        def synchronized(*args, **kwargs):
            start.wait()
            return original(*args, **kwargs)

        with patch.object(repository, method, side_effect=synchronized):
            with ThreadPoolExecutor(max_workers=len(calls)) as pool:
                responses = [pool.submit(call) for call in calls]
                return sorted((response.result(timeout=80) for response in responses), key=lambda r: r.status_code)

    def test_open_once_for_both_participants(self):
        match = super().candidate("buyer")
        pending = super().candidate("pending", "PENDING")
        rejected = super().candidate("declined", "REJECT")
        for identifier, user in ((pending, "pending"), (rejected, "declined"), (pending, "seller")):
            self.assert_status(self.open(identifier, user), 409)
        self.assert_status(self.open(pending, "outsider"), 404)
        self.assert_status(self.open("missing"), 404)
        before = self.rows("notifications")

        existing, created = self.race("open_conversation", lambda: self.open(match), lambda: self.open(match, "seller"))
        first, second = self.assert_status(created, 201), self.assert_status(existing, 200)
        self.assertEqual(first["id"], second["id"])
        self.assertEqual({first["other_user"]["id"], second["other_user"]["id"]}, {self.uids["buyer"], self.uids["seller"]})
        self.assertEqual(len(self.rows("conversations")), 1)
        self.assertIsNone(first["last_message"])
        self.assertEqual(first["created_at"], first["updated_at"])
        self.assertEqual(first["updated_at"], second["updated_at"])
        self.assertEqual(before, self.rows("notifications"))

    def test_permissions_validation_and_private_responses(self):
        url = self.prepare()
        self.assert_status(self.request("GET", url), 401)
        self.assert_status(self.request("GET", url, token="invalid"), 401)
        self.assert_status(self.request("GET", url, "outsider"), 404)
        self.assert_status(self.request("GET", url + "/mensajes", "outsider"), 404)
        self.assert_status(self.send(url, "Hola", user="outsider"), 404)
        self.assertEqual(self.assert_status(self.request("GET", "/api/conversaciones", "outsider"), 200),
                         {"items": [], "next_cursor": None})

        key = str(uuid4())
        for content in (None, 3, [], "", " \t\n", "🌍" * 2001, "\ud800"):
            self.assert_status(self.send(url, content, key), 400)
        for bad_key in (None, 1, "nada"):
            self.assert_status(self.request("POST", url + "/mensajes", "buyer", body={
                "client_message_id": bad_key, "content": "Hola",
            }), 400)
        for field in ("sender_id", "recipient_id", "sequence", "created_at"):
            self.assert_status(self.request("POST", url + "/mensajes", "buyer", body={
                "client_message_id": key, "content": "Hola", field: self.uids["seller"],
            }), 400)
        for query in ("before=0", "after=-1", "before=2&after=0", "limit=101", "limit=1&limit=2",
                      "after=9223372036854775808", "uid=other"):
            self.assert_status(self.request("GET", url + "/mensajes?" + query, "buyer"), 400)
        for query in ("limit=0", "limit=51", "cursor=no-valido", "cursor=", "uid=other"):
            self.assert_status(self.request("GET", "/api/conversaciones?" + query, "seller"), 400)
        prefix = " \n🪴 <b>Hola</b> "
        text = prefix + "é" * (2000 - len(prefix))
        message = self.assert_status(self.send(url, text, key), 201)
        self.assertEqual(message["content"], text)
        self.assertEqual(message["sender"], {"id": self.uids["buyer"], "role": "BUYER", "name": "Cuenta buyer"})
        self.assertEqual(set(message), {"id", "conversation_id", "sequence", "sender", "content", "created_at"})
        detail = self.assert_status(self.request("GET", url, "seller"), 200)
        self.assertEqual(set(detail["other_user"]), {"id", "name", "role"})
        self.assertEqual(set(detail["inmueble"]), {"id", "title", "status"})
        self.assertEqual(set(detail["last_message"]), {"id", "sender_id", "content", "created_at"})

    def test_concurrent_sends_idempotency_and_latest_summary(self):
        url = self.prepare()
        key = str(uuid4())
        first, new = self.race("send_conversation_message", lambda: self.send(url, "Hola", key),
                               lambda: self.send(url, "Hola", key.upper()))
        message = self.assert_status(new, 201)
        self.assertEqual(self.assert_status(first, 200), message)
        self.assertEqual([notice["conversation_id"] for notice in self.notices("seller")], [message["conversation_id"]])
        self.assertEqual(self.notices("buyer"), [])
        self.assert_status(self.send(url, "Distinto", key), 409)

        responses = self.race("send_conversation_message", lambda: self.send(url, "Dos"),
                              lambda: self.send(url, "Tres", key, user="seller"))
        messages = sorted((self.assert_status(r, 201) for r in responses), key=lambda m: m["sequence"])
        self.assertEqual([m["sequence"] for m in messages], [2, 3])
        detail = self.assert_status(self.request("GET", url, "seller"), 200)
        self.assertEqual(detail["last_message"]["id"], messages[-1]["id"])
        self.assertEqual(detail["updated_at"], messages[-1]["created_at"])
        self.assertEqual(len(self.notices("seller")), 2)
        self.assertEqual(len(self.notices("buyer")), 1)
        self.assertEqual(len(self.assert_status(self.request("GET", url + "/mensajes", "buyer"), 200)["items"]), 3)
        self.assertEqual(self.assert_status(self.send(url, "Hola", key), 200), message)

    def test_sequence_pages_and_distinct_homes(self):
        first = self.prepare()
        self.seed("second", "seller")
        second_match = super().candidate("buyer", identifier="second")
        second = self.assert_status(self.open(second_match, "seller"), 201)
        self.assertNotEqual(first, f"/api/conversaciones/{second['id']}")
        for i in range(1, 6):
            self.assertEqual(self.assert_status(self.send(first, str(i)), 201)["sequence"], i)

        urls = [(first + "/mensajes", {"limit": 2}, [4, 5], 4, None),
                (first + "/mensajes", {"limit": 2, "before": 4}, [2, 3], 2, None),
                (first + "/mensajes", {"limit": 2, "before": 2}, [1], None, None),
                (first + "/mensajes", {"limit": 2, "after": 0}, [1, 2], None, 2),
                (first + "/mensajes", {"limit": 2, "after": 2}, [3, 4], None, 4),
                (first + "/mensajes", {"limit": 2, "after": 4}, [5], None, None),
                (first + "/mensajes", {"after": 5}, [], None, None),
                (f"/api/conversaciones/{second['id']}/mensajes", {}, [], None, None)]
        for url, params, expected, before, after in urls:
            page = self.assert_status(self.request("GET", url, "seller", params=params), 200)
            self.assertEqual([m["sequence"] for m in page["items"]], expected)
            self.assertEqual((page["next_before"], page["next_after"]), (before, after))

        path = "/api/conversaciones"
        page = self.assert_status(self.request("GET", path, "seller", params={"limit": 1}), 200)
        self.assertEqual(page["items"][0]["inmueble"]["id"], "home")
        self.assertNotIn("created_at", page["items"][0])
        params = {"limit": 1, "cursor": page["next_cursor"]}
        self.assert_status(self.request("GET", path, "buyer", params=params), 400)
        tail = self.assert_status(self.request("GET", path, "seller", params=params), 200)
        self.assertEqual(tail["items"][0]["id"], second["id"])
        self.assertIsNone(tail["next_cursor"])

    def test_commit_failure_rolls_back_message_summary_and_notice(self):
        url = self.prepare()
        before = self.snapshot()
        key = str(uuid4())
        real_commit = Transaction._commit
        absent = self.collections["notifications"].document("detalle-confidencial")

        def commit_with_failed_precondition(transaction):
            transaction.update(absent, {"type": "MESSAGE"})
            return real_commit(transaction)

        with patch.object(Transaction, "_commit", commit_with_failed_precondition):
            error = self.assert_status(self.send(url, "texto privado", key), 500)
        self.assertEqual(set(error), {"error"})
        self.assertNotIn(absent.id, error["error"])
        self.assertNotIn("privado", error["error"])
        self.assertEqual(self.snapshot(), before)
        page = self.assert_status(self.request("GET", url + "/mensajes", "buyer"), 200)
        self.assertEqual(page["items"], [])
        self.assertEqual(self.assert_status(self.send(url, "texto privado", key), 201)["sequence"], 1)

    def test_pausing_and_closing_preserve_match_and_history(self):
        url = self.prepare()
        first = self.assert_status(self.send(url, "Hola"), 201)
        matches, selections = self.rows("matches"), self.rows("selections")
        for version, (action, status) in enumerate((("pausar", "PAUSED"), ("retirar", "CLOSED")), start=1):
            super().assert_status(self.request("POST", f"/api/inmuebles/home/{action}", "seller", body={"version": version}), 200)
            detail = self.assert_status(self.request("GET", url, "buyer"), 200)
            self.assertEqual(detail["inmueble"]["status"], status)
            self.assert_status(self.send(url, action, user="seller"), 201)
        items = self.assert_status(self.request("GET", url + "/mensajes", "buyer"), 200)["items"]
        self.assertEqual(items[0], first)
        self.assertEqual(self.rows("matches"), matches)
        self.assertEqual(self.rows("selections"), selections)

    def test_rechecks_match_for_existing_conversations(self):
        url = self.prepare()
        identifier = url.rsplit("/", 1)[1]
        self.assert_status(self.send(url, "Hola"), 201)
        self.collections["matches"].document(identifier).update({"status": "REJECTED"})
        for user in ("buyer", "seller"):
            self.assert_status(self.request("GET", url, user), 404)
            self.assert_status(self.request("GET", url + "/mensajes", user), 404)
            self.assert_status(self.send(url, "Nuevo", user=user), 404)
            page = self.assert_status(self.request("GET", "/api/conversaciones", user), 200)
            self.assertEqual(page["items"], [])


    def test_history_survives_logout_and_direct_client_access_is_denied(self):
        original_token = self.tokens["other"]
        match = self.candidate("other")
        chat = self.assert_status(self.open(match, "other"), 201)
        ref = self.collections["conversations"].document(chat["id"])
        self.addCleanup(remove_documents, ref.collection("messages"))
        path = f"/api/conversaciones/{chat['id']}/mensajes"
        message = self.assert_status(self.request("POST", path, token=original_token, body={
            "client_message_id": str(uuid4()), "content": "Historial persistente",
        }), 201)
        self.assertEqual(self.request("POST", "/api/auth/logout", token=original_token).status_code, 204)
        self.assert_status(self.request("GET", path, token=original_token), 401)
        time.sleep(1.05)
        token = self.login("other")
        restored = self.assert_status(self.request("GET", path, token=token), 200)
        self.assertEqual(restored["items"], [message])

        documents = f"http://{FIRESTORE_HOST}/v1/projects/{PROJECT}/databases/(default)/documents"
        headers = {"Authorization": f"Bearer {token}"}
        with requests.Session() as session:
            session.trust_env = False
            for path in (ref.path, ref.collection("messages").document(message["id"]).path):
                for method in ("GET", "PATCH"):
                    response = session.request(method, f"{documents}/{path}", headers=headers,
                                               json={} if method == "PATCH" else None, timeout=10)
                    self.assertEqual(response.status_code, 403)

