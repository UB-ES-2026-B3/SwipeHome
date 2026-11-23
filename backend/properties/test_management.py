"""US10: tests unitarios y de integración para consulta, edición y disponibilidad."""
import io
import json
import os
from unittest import skipUnless
from unittest.mock import MagicMock, patch
from uuid import uuid4

from PIL import Image
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, SimpleTestCase
from firebase_admin import auth
from google.auth.credentials import AnonymousCredentials
from google.cloud import firestore

from accounts import repository as repo
from properties.test_discovery import listing


def make_test_image(format="JPEG", size=(100, 100), color="blue"):
    buf = io.BytesIO()
    img = Image.new("RGB", size, color=color)
    img.save(buf, format=format)
    buf.seek(0)
    ext = "jpg" if format == "JPEG" else format.lower()
    content_type = "image/jpeg" if format == "JPEG" else f"image/{format.lower()}"
    return SimpleUploadedFile(f"photo.{ext}", buf.getvalue(), content_type=content_type)


class ManagementHttpTests(SimpleTestCase):
    def setUp(self):
        self.enterContext(patch("accounts.authentication.get_app"))
        self.verify = self.enterContext(
            patch("accounts.authentication.auth.verify_id_token",
                  return_value={"uid": "seller", "auth_time": 123})
        )
        self.enterContext(patch.object(repo, "is_session_revoked", return_value=False))
        self.profile = self.enterContext(
            patch.object(repo, "get_user_profile",
                         return_value={"role": "SELLER", "name": "Seller Name", "uid": "seller"})
        )
        self.client = Client(enforce_csrf_checks=True)

    def request(self, method, path, token="token", data=None, content_type="application/json"):
        headers = {"HTTP_AUTHORIZATION": f"Bearer {token}"} if token else {}
        if method == "get":
            return self.client.get(path, **headers)
        if content_type == "application/json":
            body = json.dumps(data) if data is not None else None
            return getattr(self.client, method)(path, body, content_type=content_type, **headers)
        return getattr(self.client, method)(path, data or {}, **headers)

    def test_authentication_and_role_requirements(self):
        endpoints = [
            ("get", "/api/inmuebles/mios"),
            ("get", "/api/inmuebles/home1/gestion"),
            ("patch", "/api/inmuebles/home1"),
            ("post", "/api/inmuebles/home1/pausar"),
            ("post", "/api/inmuebles/home1/reactivar"),
            ("post", "/api/inmuebles/home1/retirar"),
        ]
        for method, path in endpoints:
            # 401 sin sesión
            res = self.request(method, path, token=None)
            self.assertEqual(res.status_code, 401, f"Expected 401 for {method} {path}")

            # 403 con rol incorrecto (BUYER)
            self.profile.return_value = {"role": "BUYER", "uid": "buyer"}
            res = self.request(method, path, token="token")
            self.assertEqual(res.status_code, 403, f"Expected 403 for {method} {path}")
            self.profile.return_value = {"role": "SELLER", "uid": "seller"}

    def test_invalid_document_ids_and_not_found(self):
        for invalid_id in ("a" * 1501, ".", ".."):
            res = self.request("get", f"/api/inmuebles/{invalid_id}/gestion")
            self.assertEqual(res.status_code, 404)

        with patch.object(repo, "get_listing_for_management", side_effect=repo.ProposalNotFound):
            res = self.request("get", "/api/inmuebles/unknown/gestion")
            self.assertEqual(res.status_code, 404)

        with patch.object(repo, "pause_listing", side_effect=repo.ProposalNotFound):
            res = self.request("post", "/api/inmuebles/unknown/pausar")
            self.assertEqual(res.status_code, 404)

    def test_patch_validation_cannot_change_id_or_owner(self):
        valid_fields = {
            "title": "Nuevo piso", "street": "Calle Mayor 2", "city": "Barcelona",
            "postal_code": "08002", "description": "Bonito piso", "price": "1200.00",
            "surface": "80.00", "bedrooms": 3, "bathrooms": 2, "people": 4,
            "shared_accommodation": "No",
        }
        # Intentar cambiar ID
        res = self.request("patch", "/api/inmuebles/home1", data={**valid_fields, "id": "different"})
        self.assertEqual(res.status_code, 400)
        self.assertIn("id", res.json().get("errors", {}))

        # Intentar cambiar propietario (seller_uid / owner)
        res = self.request("patch", "/api/inmuebles/home1", data={**valid_fields, "seller_uid": "other_seller"})
        self.assertEqual(res.status_code, 400)
        self.assertIn("seller_uid", res.json().get("errors", {}))

    def test_patch_validation_photos_and_version(self):
        valid_fields = {
            "title": "Nuevo piso", "street": "Calle Mayor 2", "city": "Barcelona",
            "postal_code": "08002", "description": "Bonito piso", "price": "1200.00",
            "surface": "80.00", "bedrooms": 3, "bathrooms": 2, "people": 4,
            "shared_accommodation": "No",
        }
        existing_listing = {
            "id": "home1",
            "seller_uid": "seller",
            "title": "Piso original",
            "street": "Calle Antigua 1",
            "city": "Madrid",
            "postal_code": "28001",
            "description": "Descripción original",
            "price_cents": 100000,
            "surface_hundredths": 7000,
            "bedrooms": 2,
            "bathrooms": 1,
            "people": 3,
            "shared_accommodation": False,
            "photos": ["https://example.com/photo1.jpg"],
            "published": True,
            "availability": "ACTIVE",
            "version": 1,
        }
        # Fotos vacías
        res = self.request("patch", "/api/inmuebles/home1", data={**valid_fields, "photos": []})
        self.assertEqual(res.status_code, 400)

        # Versión inválida
        res = self.request("patch", "/api/inmuebles/home1", data={**valid_fields, "version": "invalido"})
        self.assertEqual(res.status_code, 400)

        # Conflicto de versión (409)
        with patch.object(repo, "get_listing", return_value=existing_listing):
            with patch.object(repo, "update_listing_full", side_effect=repo.VersionConflict):
                res = self.request("patch", "/api/inmuebles/home1", data={**valid_fields, "version": 1})
                self.assertEqual(res.status_code, 409)

        # Error interno 500 no expone secretos
        with patch.object(repo, "get_listing", return_value=existing_listing):
            with patch.object(repo, "update_listing_full", side_effect=RuntimeError("database password 123")):
                res = self.request("patch", "/api/inmuebles/home1", data=valid_fields)
                self.assertEqual(res.status_code, 500)
                self.assertNotIn("password", res.content.decode())


@skipUnless(os.environ.get("FIRESTORE_EMULATOR_HOST"), "Requiere emulador local de Firestore")
class ManagementFirestoreTests(SimpleTestCase):
    def setUp(self):
        self.assertTrue(os.environ["FIRESTORE_EMULATOR_HOST"].startswith(("127.0.0.1:", "localhost:")))
        self.db = firestore.Client(project="demo-swipehome-us4", credentials=AnonymousCredentials())
        self.addCleanup(self.db.close)
        prefix = uuid4().hex
        for name in (
            "LISTINGS", "SWIPES", "MATCHES", "NOTIFICATIONS", "PROPOSALS",
            "SELECTIONS", "PROPOSAL_REQUESTS", "SELECTION_EVENTS", "USERS"
        ):
            self.enterContext(patch.object(repo, name + "_COLLECTION", prefix + name))

        self.enterContext(patch("accounts.repository.get_app"))
        self.enterContext(patch("accounts.repository.firestore.client", return_value=self.db))
        self.enterContext(patch("accounts.authentication.get_app"))
        self.enterContext(patch("properties.match_service.get_app"))
        self.enterContext(
            patch("accounts.authentication.auth.verify_id_token",
                  side_effect=lambda token, **kw: {"uid": token, "auth_time": 123})
        )
        self.enterContext(patch.object(repo, "is_session_revoked", return_value=False))
        self.enterContext(
            patch.object(repo, "get_user_profile",
                         side_effect=lambda uid: {
                             "role": "SELLER" if uid.startswith("seller") else "BUYER",
                             "name": f"User {uid}", "uid": uid
                         })
        )
        self.client = Client(enforce_csrf_checks=True)

        # Mock Azure Blob container client
        self.mock_container = MagicMock()
        self.mock_container.container_name = "listings"
        self.mock_blob = MagicMock()
        self.mock_blob.url = "https://azure.storage/listings/seller/mock_blob.jpg"
        self.mock_container.get_blob_client.return_value = self.mock_blob
        self.enterContext(patch.object(repo, "get_container_client", return_value=self.mock_container))

        # Crear inmueble de prueba
        self.col("LISTINGS").document("home1").create(listing(
            seller_uid="seller1",
            photos=["https://example.com/photo1.jpg", "https://example.com/photo2.jpg"],
            version=1,
            availability="ACTIVE",
        ))

    def col(self, name):
        return self.db.collection(getattr(repo, name + "_COLLECTION"))

    def auth_headers(self, uid):
        return {"HTTP_AUTHORIZATION": f"Bearer {uid}"}

    def test_ca01_my_listings_query_isolation_and_actions(self):
        # Otro vendedor con su propio inmueble
        self.col("LISTINGS").document("home_other").create(listing(
            seller_uid="seller2",
            photos=["https://example.com/other.jpg"],
            version=1,
            availability="ACTIVE",
        ))
        res = self.client.get("/api/inmuebles/mios", **self.auth_headers("seller1"))
        self.assertEqual(res.status_code, 200)
        items = res.json()["items"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["id"], "home1")
        self.assertEqual(items[0]["availability"], "ACTIVE")
        self.assertEqual(items[0]["version"], 1)
        self.assertTrue(items[0]["can_edit"])
        self.assertTrue(items[0]["can_pause"])
        self.assertFalse(items[0]["can_reactivate"])
        self.assertTrue(items[0]["can_withdraw"])
        self.assertIn("edit", items[0]["actions"])
        self.assertIn("pause", items[0]["actions"])
        self.assertIn("withdraw", items[0]["actions"])

        # Consultar detalle para gestión
        detail_res = self.client.get("/api/inmuebles/home1/gestion", **self.auth_headers("seller1"))
        self.assertEqual(detail_res.status_code, 200)
        detail = detail_res.json()
        self.assertEqual(detail["id"], "home1")
        self.assertEqual(len(detail["photos"]), 2)
        self.assertEqual(detail["version"], 1)

        # seller2 no puede gestionar home1 (404)
        alien_res = self.client.get("/api/inmuebles/home1/gestion", **self.auth_headers("seller2"))
        self.assertEqual(alien_res.status_code, 404)

    def test_ca02_ca03_edit_listing_data_and_photos(self):
        edit_data = {
            "title": "Piso reformado y luminoso",
            "street": "Calle Mayor 10",
            "city": "Barcelona",
            "postal_code": "08005",
            "description": "Totalmente amueblado y reformado",
            "price": "1100.00",
            "surface": "75.00",
            "bedrooms": 3,
            "bathrooms": 2,
            "people": 4,
            "shared_accommodation": "Sí",
            "photos": ["https://example.com/photo2.jpg"],  # Retiramos photo1 y conservamos photo2
            "version": 1,
        }
        res = self.client.patch(
            "/api/inmuebles/home1",
            json.dumps(edit_data),
            content_type="application/json",
            **self.auth_headers("seller1"),
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["title"], "Piso reformado y luminoso")
        self.assertEqual(data["photos"], ["https://example.com/photo2.jpg"])
        self.assertEqual(data["version"], 2)

        # Verificar persistencia en base de datos
        snap = self.col("LISTINGS").document("home1").get().to_dict()
        self.assertEqual(snap["title"], "Piso reformado y luminoso")
        self.assertEqual(snap["version"], 2)
        self.assertEqual(snap["photos"], ["https://example.com/photo2.jpg"])

        # Intentar editar conservando una foto ajena al anuncio -> 400
        alien_photo_data = {**edit_data, "photos": ["https://example.com/alien_photo.jpg"], "version": 2}
        res_alien = self.client.patch(
            "/api/inmuebles/home1",
            json.dumps(alien_photo_data),
            content_type="application/json",
            **self.auth_headers("seller1"),
        )
        self.assertEqual(res_alien.status_code, 400)

        # Intentar editar con versión desactualizada (enviar version 1 cuando ya es 2) -> 409
        stale_data = {**edit_data, "title": "Intento desactualizado", "version": 1}
        res_conflict = self.client.patch(
            "/api/inmuebles/home1",
            json.dumps(stale_data),
            content_type="application/json",
            **self.auth_headers("seller1"),
        )
        self.assertEqual(res_conflict.status_code, 409)

    def test_ca04_pause_and_reactivate(self):
        # 1. Pausar anuncio activo
        res_pause = self.client.post("/api/inmuebles/home1/pausar", **self.auth_headers("seller1"))
        self.assertEqual(res_pause.status_code, 200)
        self.assertEqual(res_pause.json()["availability"], "PAUSED")
        self.assertEqual(res_pause.json()["version"], 2)

        # Reintento idéntico de pausa -> 200 idempotente
        res_pause_retry = self.client.post("/api/inmuebles/home1/pausar", **self.auth_headers("seller1"))
        self.assertEqual(res_pause_retry.status_code, 200)
        self.assertEqual(res_pause_retry.json()["availability"], "PAUSED")

        # Comprobación de que no aparece en el explorador
        self.col("USERS").document("buyer1").set({"role": "BUYER", "name": "Comprador 1"})
        res_explore = self.client.get("/api/inmuebles/explorar", **self.auth_headers("buyer1"))
        self.assertEqual(res_explore.status_code, 200)
        self.assertNotIn("home1", [item["id"] for item in res_explore.json()["items"]])

        # Intento de swipe sobre anuncio pausado -> 409 DecisionConflict
        res_swipe = self.client.post(
            "/api/inmuebles/home1/decision",
            json.dumps({"decision": "LIKE"}),
            content_type="application/json",
            **self.auth_headers("buyer1"),
        )
        self.assertEqual(res_swipe.status_code, 409)

        # 2. Reactivar anuncio
        res_reactivate = self.client.post("/api/inmuebles/home1/reactivar", **self.auth_headers("seller1"))
        self.assertEqual(res_reactivate.status_code, 200)
        self.assertEqual(res_reactivate.json()["availability"], "ACTIVE")
        self.assertEqual(res_reactivate.json()["version"], 3)

        # Reintento idéntico de reactivación -> 200 idempotente
        res_reactivate_retry = self.client.post("/api/inmuebles/home1/reactivar", **self.auth_headers("seller1"))
        self.assertEqual(res_reactivate_retry.status_code, 200)
        self.assertEqual(res_reactivate_retry.json()["availability"], "ACTIVE")

        # Ahora el comprador que no lo había valorado puede verlo en explorador
        res_explore2 = self.client.get("/api/inmuebles/explorar", **self.auth_headers("buyer1"))
        self.assertEqual(res_explore2.status_code, 200)
        self.assertIn("home1", [item["id"] for item in res_explore2.json()["items"]])

    def test_ca05_withdraw_listing_and_notifications(self):
        # Crear candidatos y matches previos
        self.col("USERS").document("buyer1").set({"role": "BUYER", "name": "Buyer 1"})
        self.col("USERS").document("buyer2").set({"role": "BUYER", "name": "Buyer 2"})

        # buyer1 hace LIKE -> match PENDING
        _, match1, _ = repo.record_decision("buyer1", "home1", "LIKE", buyer_name="Buyer 1")
        # buyer2 hace LIKE y seller confirma -> match CONFIRMED
        _, match2, _ = repo.record_decision("buyer2", "home1", "LIKE", buyer_name="Buyer 2")
        repo.record_seller_decision("seller1", match2["id"], "LIKE")

        # Retirar anuncio
        res_withdraw = self.client.post("/api/inmuebles/home1/retirar", **self.auth_headers("seller1"))
        self.assertEqual(res_withdraw.status_code, 200)
        self.assertEqual(res_withdraw.json()["availability"], "CLOSED")
        self.assertEqual(res_withdraw.json()["closure_reason"], "WITHDRAWN")

        # Reintento idéntico de retirada -> 200 idempotente
        res_withdraw_retry = self.client.post("/api/inmuebles/home1/retirar", **self.auth_headers("seller1"))
        self.assertEqual(res_withdraw_retry.status_code, 200)
        self.assertEqual(res_withdraw_retry.json()["availability"], "CLOSED")
        self.assertEqual(res_withdraw_retry.json()["closure_reason"], "WITHDRAWN")

        # No se puede reabrir un anuncio cerrado -> 409
        res_reopen = self.client.post("/api/inmuebles/home1/reactivar", **self.auth_headers("seller1"))
        self.assertEqual(res_reopen.status_code, 409)

        # No se puede pausar un anuncio cerrado -> 409
        res_pause_closed = self.client.post("/api/inmuebles/home1/pausar", **self.auth_headers("seller1"))
        self.assertEqual(res_pause_closed.status_code, 409)

        # Anuncio cerrado está en modo solo lectura para edición -> 409
        edit_fields = {
            "title": "Intento de edición en cerrado", "street": "Calle 1", "city": "Barcelona",
            "postal_code": "08001", "description": "Desc", "price": "900.00", "surface": "50.00",
            "bedrooms": 1, "bathrooms": 1, "people": 1, "shared_accommodation": "No",
        }
        res_edit_closed = self.client.patch(
            "/api/inmuebles/home1",
            json.dumps(edit_fields),
            content_type="application/json",
            **self.auth_headers("seller1"),
        )
        self.assertEqual(res_edit_closed.status_code, 409)

        # Avisos de indisponibilidad generados para buyer1 y buyer2
        notices = [s.to_dict() for s in self.col("NOTIFICATIONS").stream() if s.to_dict().get("listing_id") == "home1"]
        closed_notices = [n for n in notices if n.get("type") == "LISTING_CLOSED"]
        recipients = {n["recipient_uid"] for n in closed_notices}
        self.assertEqual(recipients, {"buyer1", "buyer2"})
        for n in closed_notices:
            self.assertIn("Retirada por el propietario", n["message"])

        # Historial de decisiones y matches se conserva
        swipes = list(self.col("SWIPES").stream())
        self.assertGreaterEqual(len(swipes), 2)
        matches = list(self.col("MATCHES").stream())
        self.assertGreaterEqual(len(matches), 2)

    def test_ca06_pending_selection_proposal_blocks_edition_and_availability(self):
        # Crear match confirmado
        self.col("USERS").document("buyer1").set({"role": "BUYER", "name": "Buyer 1"})
        _, match, _ = repo.record_decision("buyer1", "home1", "LIKE", buyer_name="Buyer 1")
        repo.record_seller_decision("seller1", match["id"], "LIKE")

        # Crear propuesta de selección PENDING
        proposal, created = repo.create_proposal("seller1", "home1", match["id"], "req-123")
        self.assertTrue(created)

        # Mientras existe propuesta pendiente, no se puede editar
        edit_fields = {
            "title": "Intento con propuesta pendiente", "street": "Calle 1", "city": "Barcelona",
            "postal_code": "08001", "description": "Desc", "price": "900.00", "surface": "50.00",
            "bedrooms": 1, "bathrooms": 1, "people": 1, "shared_accommodation": "No",
        }
        res_edit = self.client.patch(
            "/api/inmuebles/home1",
            json.dumps(edit_fields),
            content_type="application/json",
            **self.auth_headers("seller1"),
        )
        self.assertEqual(res_edit.status_code, 409)

        # Tampoco se puede pausar ni retirar
        res_pause = self.client.post("/api/inmuebles/home1/pausar", **self.auth_headers("seller1"))
        self.assertEqual(res_pause.status_code, 409)

        res_withdraw = self.client.post("/api/inmuebles/home1/retirar", **self.auth_headers("seller1"))
        self.assertEqual(res_withdraw.status_code, 409)

        # En la consulta de gestión se indica has_pending_proposal: True y can_edit: False
        res_mgmt = self.client.get("/api/inmuebles/home1/gestion", **self.auth_headers("seller1"))
        self.assertEqual(res_mgmt.status_code, 200)
        self.assertTrue(res_mgmt.json()["has_pending_proposal"])
        self.assertFalse(res_mgmt.json()["can_edit"])
        self.assertEqual(res_mgmt.json()["actions"], [])

    def test_ca09_multipart_photo_edition_and_cleanup(self):
        from django.test.client import encode_multipart, BOUNDARY, MULTIPART_CONTENT

        new_img = make_test_image("JPEG")
        form_data = {
            "title": "Piso con nueva foto",
            "street": "Calle Mayor 1",
            "city": "Barcelona",
            "postal_code": "08001",
            "description": "Descripción",
            "price": "950.00",
            "surface": "65.00",
            "bedrooms": "2",
            "bathrooms": "1",
            "people": "3",
            "shared_accommodation": "No",
            "existing_photos": "https://example.com/photo1.jpg",
            "photos": new_img,
            "version": "1",
        }
        body = encode_multipart(BOUNDARY, form_data)
        res = self.client.patch(
            "/api/inmuebles/home1",
            body,
            content_type=MULTIPART_CONTENT,
            **self.auth_headers("seller1"),
        )
        self.assertEqual(res.status_code, 200, res.json())
        data = res.json()
        self.assertEqual(data["version"], 2)
        self.assertIn("https://example.com/photo1.jpg", data["photos"])
        self.assertIn("https://azure.storage/listings/seller/mock_blob.jpg", data["photos"])
