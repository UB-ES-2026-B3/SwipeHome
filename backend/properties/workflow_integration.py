"""Integraciones HTTP con Auth, Firestore y almacenamiento de QA."""
from unittest.mock import patch

from google.api_core.exceptions import ServiceUnavailable

from accounts import repository
from properties.tests import image_file, jpeg
from qa.environment import BLOB_ENDPOINT, blob_container
from qa.fixtures import EmulatorFixture


class WorkflowIntegrationTests(EmulatorFixture):
    def test_publication_azurite_photos_survive_confirmed_match(self):
        photos = [jpeg("first.jpg"), image_file("second.png", "PNG", "image/png")]
        contents = [photo.read() for photo in photos]
        for photo in photos:
            photo.seek(0)
        identifier, listing = self.publish(photos=photos, title="Anuncio con dos fotos reales")
        self.assertEqual(len(listing["photos"]), 2)
        container = blob_container()
        for url, data, content_type in zip(listing["photos"], contents, ("image/jpeg", "image/png"), strict=True):
            prefix = f"{BLOB_ENDPOINT}/listings/"
            self.assertTrue(url.startswith(prefix), url)
            blob = container.get_blob_client(url.removeprefix(prefix))
            self.assertEqual(blob.get_blob_properties().content_settings.content_type, content_type)
            self.assertEqual(blob.download_blob().readall(), data)

        match_id = self.candidate("buyer", identifier=identifier)
        for user in ("buyer", "seller"):
            page = self.assert_status(self.request("GET", "/api/matches", user), 200)
            self.assertEqual([item["id"] for item in page["items"]], [match_id])
            self.assertEqual(page["items"][0]["listing"]["photos"], listing["photos"])
        notices = self.assert_status(self.request("GET", "/api/notificaciones", "buyer"), 200)
        self.assertEqual([row["listing"]["id"] for row in notices["items"]], [identifier])
        self.assertEqual(self.assert_status(self.request("GET", "/api/matches", "other"), 200)["items"], [])

    def test_failed_firestore_publication_compensates_real_blobs(self):
        container = blob_container()
        prefix = self.uids["seller"] + "/"
        original = self.rows("listings")
        existing = {blob.name for blob in container.list_blobs(name_starts_with=prefix)}
        with patch("google.cloud.firestore_v1.document.DocumentReference.create",
                   side_effect=ServiceUnavailable("Fallo de escritura inyectado")) as commit:
            self.assert_status(self.publish_response(photos=[jpeg("one.jpg"), jpeg("two.jpg")]), 500)
            commit.assert_called_once()
        self.assertEqual(self.rows("listings"), original)
        self.assertEqual({blob.name for blob in container.list_blobs(name_starts_with=prefix)}, existing)

    def test_preferences_invalidate_cursor_and_survive_new_auth_session(self):
        self.seed("affordable", "other_seller", price_cents=45000)
        start = self.assert_status(self.request("GET", "/api/inmuebles/explorar", "buyer", params={"limit": 1}), 200)
        cursor = start["next_cursor"]
        self.assertTrue(cursor)
        filters = self.assert_status(self.request("GET", "/api/auth/preferences", "buyer"), 200)["filters"]
        saved = self.assert_status(self.request(
            "PUT", "/api/auth/preferences", "buyer", body={**filters, "price_max": "600"},
        ), 200)["filters"]
        self.assertEqual(saved["price_max"], "600.00")
        self.assert_status(self.request("GET", "/api/inmuebles/explorar", "buyer", params={"cursor": cursor}), 400)
        token = self.login("buyer")
        fetched = self.assert_status(self.request("GET", "/api/auth/preferences", token=token), 200)
        self.assertEqual(fetched["filters"], saved)
        page = self.assert_status(self.request("GET", "/api/inmuebles/explorar", token=token), 200)
        self.assertEqual([item["id"] for item in page["items"]], ["affordable"])
        other = self.assert_status(self.request("GET", "/api/inmuebles/explorar", "other"), 200)
        self.assertEqual({item["id"] for item in other["items"]}, {"home", "affordable"})
        self.assert_status(self.request("PUT", "/api/auth/preferences", "seller", body=filters), 403)

    def test_pending_proposal_on_another_home_stays_private_after_acceptance(self):
        self.seed("second", "seller")
        self.candidate("buyer")
        self.candidate("other", identifier="second")
        first = self.assert_status(self.propose(), 201)["id"]
        second = self.assert_status(self.propose("other", identifier="second"), 201)["id"]
        candidates = self.rows("swipes")
        matches = self.rows("matches")
        self.assert_status(self.decide(first, "ACCEPT"), 201)
        self.assert_status(self.request("GET", f"/api/propuestas/{first}", "other"), 404)
        page = self.assert_status(self.request("GET", "/api/propuestas", "other"), 200)
        self.assertEqual([(item["id"], item["status"]) for item in page["items"]], [(second, "PENDING")])
        home = self.rows("listings")["second"]
        self.assertEqual(home["pending_selection_id"], second)
        self.assertIs(home["published"], True)
        self.assertEqual(self.rows("swipes"), candidates)
        self.assertEqual(self.rows("matches"), matches)
