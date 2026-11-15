"""Persistencia y exploración US8 con Firestore Emulator aislado."""
import json
import os
from unittest import skipUnless
from unittest.mock import patch
from django.test import SimpleTestCase
from google.cloud.firestore_v1.batch import WriteBatch
from accounts import repository
from properties.preferences import validate_preferences
from properties import test_firestore as base
from properties.test_discovery import listing


@skipUnless(os.environ.get("FIRESTORE_EMULATOR_HOST"), "Requiere Firestore Emulator local.")
class FirestorePreferenceTests(SimpleTestCase):
    collection = base.FirestoreDecisionTests.collection
    seed = base.FirestoreDecisionTests.seed
    post = base.FirestoreDecisionTests.post
    explore = base.FirestoreDecisionTests.explore
    rows = base.FirestoreDecisionTests.rows
    counts = base.FirestoreDecisionTests.counts

    def setUp(self):
        base.FirestoreDecisionTests.setUp(self)
        self.collections["PREFERENCES_COLLECTION"] = self.prefix + "_preferences"
        self.enterContext(patch.object(repository, "PREFERENCES_COLLECTION", self.collections["PREFERENCES_COLLECTION"]))
        # Solo los documentos de este caso; no se limpian colecciones compartidas.
        self.addCleanup(self.clean)

    def clean(self):
        for name in self.collections.values():
            for snap in self.db.collection(name).stream():
                snap.reference.delete()

    def prefs(self, body=None, method="get", uid="buyer"):
        kwargs = {"HTTP_AUTHORIZATION": "Bearer " + uid}
        if method == "put":
            kwargs.update(data=json.dumps(body), content_type="application/json")
        return getattr(self.client, method)("/api/exploracion/filtros", **kwargs)

    def put(self, body, uid="buyer"):
        response = self.prefs(body, "put", uid)
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def ids(self, **query):
        response = self.explore(**query)
        self.assertEqual(response.status_code, 200, response.content)
        return [row["id"] for row in response.json()["items"]]

    def test_initial_replace_omitted_null_empty_and_delete_idempotence(self):
        empty = validate_preferences({})[0]
        self.assertEqual(self.prefs().json(), empty)
        self.assertFalse(self.collection("preferences").document("buyer").get().exists)
        body = {"city": " Barcelona ", "postal_code": " 08001 ", "min_price": "0",
                "max_price": "950.50", "min_area": "65.5", "max_area": "65.50", "bedrooms": 2,
                "min_bathrooms": 1, "people_offered": 3, "is_shared": False}
        canonical = self.put(body)
        self.assertEqual(canonical, validate_preferences(body)[0])
        self.assertEqual(self.prefs().json(), canonical)
        self.assertEqual(self.collection("preferences").document("buyer").get().to_dict(), canonical)
        self.assertEqual(self.put({"bedrooms": 0}), {**empty, "bedrooms": 0})
        self.assertEqual(self.put(dict.fromkeys(body)), empty)
        self.put(body)
        self.assertEqual(self.put({}), empty)
        for _ in range(2):
            response = self.prefs(method="delete")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), empty)

    def test_filters_individually_and_together_with_exact_boundaries(self):
        cases = [({"city": "Barcelona"}, {"city": "Madrid"}),
                 ({"postal_code": "08001"}, {"postal_code": "AB 01"}),
                 ({"min_price": "950.50"}, {"price_cents": 95049}),
                 ({"max_price": "950.50"}, {"price_cents": 95051}),
                 ({"min_area": "65.50"}, {"surface_hundredths": 6549}),
                 ({"max_area": "65.50"}, {"surface_hundredths": 6551}),
                 ({"bedrooms": 2}, {"bedrooms": 0}),
                 ({"min_bathrooms": 2}, {"bathrooms": 1}),
                 ({"people_offered": 3}, {"people": 2}),
                 ({"is_shared": False}, {"shared_accommodation": True})]
        self.collection("listings").document("home").update({"bathrooms": 2})
        all_filters = {}
        for index, (body, change) in enumerate(cases):
            identifier = "outside-" + str(index)
            self.seed(identifier, bathrooms=change.get("bathrooms", 2), **{k: v for k, v in change.items() if k != "bathrooms"})
            self.put(body)
            ids = self.ids()
            self.assertIn("home", ids)
            self.assertNotIn(identifier, ids)
            self.collection("listings").document(identifier).delete()
            all_filters.update(body)
        self.put(all_filters)
        self.assertEqual(self.ids(), ["home"])
        self.put({"is_shared": True, "people_offered": 3})
        self.assertEqual(self.ids(), [])
        self.seed("shared", shared_accommodation=True)
        self.assertEqual(self.ids(), ["shared"])
        self.put({"bedrooms": 0})
        self.assertEqual(self.ids(), [])
        self.seed("studio", bedrooms=0)
        self.assertEqual(self.ids(), ["studio"])
        self.put({"city": "Barcelona", "postal_code": " AB 01 "})
        self.seed("postal", postal_code="AB 01")
        self.assertEqual(self.ids(), ["postal"])
        self.put({"min_price": "950.50", "max_price": "950.50", "min_area": "65.50", "max_area": "65.50"})
        self.assertEqual(set(self.ids()), {"home", "shared", "studio", "postal"})

    def test_and_combinations_empty_matches_and_options_independent_of_filters(self):
        self.seed("madrid", city=" Madrid ", postal_code="08002")
        self.seed("duplicate", city="Barcelona")
        self.seed("draft", city="Valencia", published=False)
        self.seed("incomplete", city="Bilbao", photos=[])
        self.seed("empty", city=" ")
        self.put({"city": "Madrid", "postal_code": "08001"})
        self.assertEqual(self.explore().json(), {"items": [], "next_cursor": None})
        options = self.client.get("/api/inmuebles/opciones-filtro", HTTP_AUTHORIZATION="Bearer buyer")
        self.assertEqual(options.status_code, 200)
        self.assertEqual(options.json(), {"cities": ["Barcelona", "Madrid"]})
        self.put({"city": "Madrid"})
        self.assertEqual(self.ids(), ["madrid"])
        self.put({"postal_code": "08001"})
        self.assertEqual(set(self.ids()), {"home", "duplicate"})

    def test_decisions_other_buyers_reset_and_isolation(self):
        self.seed("passed")
        self.seed("other")
        self.seed("available", city="Madrid")
        self.assertEqual(self.post().status_code, 201)
        self.assertEqual(self.post("PASS", identifier="passed").status_code, 201)
        self.assertEqual(self.post(uid="buyer2", identifier="other").status_code, 201)
        counts = self.counts()
        self.put({"city": "Barcelona"})
        other_preferences = self.put({"city": "Madrid"}, "buyer2")
        self.assertEqual(self.ids(), ["other"])
        self.assertEqual(self.ids(uid="buyer2"), ["available"])
        self.assertEqual(self.prefs(method="delete").status_code, 200)
        self.assertEqual(set(self.ids()), {"other", "available"})
        self.assertEqual(self.prefs(uid="buyer2").json(), other_preferences)
        self.assertEqual(self.counts(), counts)
        self.assertEqual(self.rows("matches")[0].to_dict()["status"], "PENDING")

    def test_tied_pagination_multiple_batches_and_configuration_bound_cursors(self):
        batch = self.db.batch()
        for i in range(65):
            batch.create(self.collection("listings").document(f"z-{i:03}"), listing(city="Madrid"))
        for i in range(5):
            batch.create(self.collection("listings").document(f"a-{i}"), listing(city="Barcelona"))
        batch.commit()
        self.put({"city": "Barcelona", "min_price": "0"})
        response = self.explore(limit="2")
        self.assertEqual(response.status_code, 200)
        first = response.json()
        ids = [row["id"] for row in first["items"]]
        cursor = first["next_cursor"]
        while cursor:
            response = self.explore(limit="2", cursor=cursor)
            self.assertEqual(response.status_code, 200)
            page = response.json()
            ids.extend(row["id"] for row in page["items"])
            cursor = page["next_cursor"]
        self.assertEqual(ids, ["home", "a-4", "a-3", "a-2", "a-1", "a-0"])
        self.assertEqual(len(ids), len(set(ids)))
        cursor = first["next_cursor"]
        self.assertEqual(self.explore(cursor=cursor + "bad").status_code, 400)
        self.put({"city": "Barcelona", "min_price": "0"}, "buyer2")
        self.assertEqual(self.explore(uid="buyer2", cursor=cursor).status_code, 400)
        self.put({"city": " Barcelona ", "min_price": "0.00"})
        self.assertEqual(self.explore(cursor=cursor).status_code, 200)
        self.put({"city": "Madrid"})
        self.assertEqual(self.explore(cursor=cursor).status_code, 400)
        self.assertEqual(self.ids(limit="1"), ["z-064"])
        self.prefs(method="delete")
        self.assertEqual(self.explore(cursor=cursor).status_code, 400)
        self.assertEqual(self.ids(limit="1"), ["z-064"])

    def test_validation_and_rejected_commit_preserve_entire_document(self):
        original = self.put({"city": "Barcelona", "bedrooms": 0, "is_shared": False})
        response = self.prefs({"city": "Madrid", "max_price": "0"}, "put")
        self.assertEqual(response.status_code, 400)
        self.assertIn("max_price", response.json()["errors"])
        self.assertEqual(self.prefs().json(), original)
        # DocumentReference.set prepara un WriteBatch; fallo antes del commit remoto.
        with patch.object(WriteBatch, "commit", side_effect=RuntimeError("before commit")):
            self.assertEqual(self.prefs({"city": "Madrid"}, "put").status_code, 500)
            self.assertEqual(self.prefs(method="delete").status_code, 500)
        self.assertEqual(self.collection("preferences").document("buyer").get().to_dict(), original)

    def test_saved_preferences_survive_explore_failure_and_retry(self):
        saved = self.put({"city": "Barcelona"})
        with patch("accounts.repository.get_pending_listings", side_effect=RuntimeError("network")):
            self.assertEqual(self.explore().status_code, 500)
        self.assertEqual(self.prefs().json(), saved)
        self.assertEqual(self.ids(), ["home"])
        self.assertEqual(self.prefs().json(), saved)
