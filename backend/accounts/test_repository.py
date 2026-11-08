import os
from decimal import Decimal
from unittest.mock import MagicMock, patch

from azure.storage.blob import ContentSettings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase
from firebase_admin import firestore
from google.api_core.exceptions import AlreadyExists, ServiceUnavailable

from . import azure_storage, repository
from .azure_storage import StorageConfigError

UID = "uid-de-prueba-123"


@patch("accounts.repository.get_app")
@patch("accounts.repository.firestore.client")
class CreateUserProfileTests(SimpleTestCase):
    def document(self, client):
        return client.return_value.collection.return_value.document.return_value

    def test_writes_document_with_uid_as_id_in_users_collection(self, client, get_app):
        profile = repository.create_user_profile(UID, name="Ana García", email="ana@example.com", role="BUYER")

        client.assert_called_once_with(app=get_app.return_value)
        client.return_value.collection.assert_called_once_with("users")
        client.return_value.collection.return_value.document.assert_called_once_with(UID)
        self.document(client).create.assert_called_once_with({
            "name": "Ana García",
            "email": "ana@example.com",
            "role": "BUYER",
            "created_at": firestore.SERVER_TIMESTAMP,
        })
        self.assertEqual(profile, {"uid": UID, "name": "Ana García", "email": "ana@example.com", "role": "BUYER"})

    def test_stores_normalized_email(self, client, get_app):
        profile = repository.create_user_profile(UID, name="Ana", email="  Ana@Example.COM ", role="SELLER")
        written = self.document(client).create.call_args.args[0]
        self.assertEqual(written["email"], "ana@example.com")
        self.assertEqual(profile["email"], "ana@example.com")

    def test_never_overwrites_with_set(self, client, get_app):
        repository.create_user_profile(UID, name="Ana", email="ana@example.com", role="BUYER")
        self.document(client).set.assert_not_called()

    def test_firestore_errors_propagate_for_compensation(self, client, get_app):
        for error in (ServiceUnavailable("caído"), AlreadyExists("ya existe")):
            with self.subTest(error=type(error).__name__):
                self.document(client).create.side_effect = error
                with self.assertRaises(type(error)):
                    repository.create_user_profile(UID, name="Ana", email="ana@example.com", role="BUYER")


@patch("accounts.repository.get_app")
@patch("accounts.repository.firestore.client")
class GetUserProfileTests(SimpleTestCase):
    def setUp(self):
        from types import SimpleNamespace
        self.user = self.enterContext(patch(
            "accounts.repository.auth.get_user",
            return_value=SimpleNamespace(display_name=None, email="ana@example.com"),
        ))

    def snapshot(self, client, exists, data=None):
        snapshot = MagicMock(exists=exists)
        snapshot.to_dict.return_value = data
        client.return_value.collection.return_value.document.return_value.get.return_value = snapshot
        return snapshot

    def test_reads_document_by_uid(self, client, get_app):
        self.snapshot(client, True, {"name": "Ana", "email": "ana@example.com", "role": "SELLER"})
        profile = repository.get_user_profile(UID)
        client.return_value.collection.assert_called_once_with("users")
        client.return_value.collection.return_value.document.assert_called_once_with(UID)
        self.assertEqual(profile, {"uid": UID, "name": "Ana", "email": "ana@example.com", "role": "SELLER"})

    def test_missing_document_returns_none(self, client, get_app):
        self.snapshot(client, False)
        self.assertIsNone(repository.get_user_profile(UID))

    def test_only_contract_fields_are_returned(self, client, get_app):
        self.snapshot(client, True, {
            "name": "Ana", "email": "ana@example.com", "role": "BUYER",
            "created_at": object(), "campo_interno": "no debe salir",
        })
        self.assertEqual(set(repository.get_user_profile(UID)), {"uid", "name", "email", "role"})


VALUES = {
    "title": "Piso",
    "street": "Calle 1",
    "city": "Barcelona",
    "postal_code": "08001",
    "description": "Descripción",
    "price": Decimal("950.50"),
    "surface": Decimal("65.50"),
    "bedrooms": 2,
    "bathrooms": 1,
    "people": 3,
    "shared_accommodation": False,
}
BLOB_URL = "https://swipehome.blob.core.windows.net/listings/" + UID + "/abc"


@patch("accounts.repository.get_app")
@patch("accounts.repository.firestore.client")
@patch("accounts.repository.get_container_client")
class CreateListingTests(SimpleTestCase):
    def reference(self, client):
        return client.return_value.collection.return_value.document.return_value

    def blob(self, container):
        blob = container.return_value.get_blob_client.return_value
        blob.url = BLOB_URL
        return blob

    def photo(self, name="one.jpg", content_type="image/jpeg"):
        return SimpleUploadedFile(name, b"data", content_type=content_type)

    def test_writes_listing_to_firestore_with_verified_seller(self, container, client, get_app):
        reference = self.reference(client)
        reference.id = "listing-123"
        self.blob(container)

        result = repository.create_listing(UID, values=dict(VALUES), photos=[self.photo()])

        client.assert_called_once_with(app=get_app.return_value)
        client.return_value.collection.assert_called_once_with("listings")
        reference.create.assert_called_once()
        written = reference.create.call_args.args[0]
        self.assertEqual(written["seller_uid"], UID)
        self.assertEqual(written["price_cents"], 95050)
        self.assertEqual(written["surface_hundredths"], 6550)
        # Se guarda la URL pública del blob, sin token ni SAS.
        self.assertEqual(written["photos"], [BLOB_URL])
        self.assertEqual(result, {"id": "listing-123"})

    def test_uploads_each_photo_with_its_content_type_and_naming(self, container, client, get_app):
        blobs = [MagicMock(url=f"https://example/{index}") for index in range(2)]
        container.return_value.get_blob_client.side_effect = blobs
        photos = [self.photo("one.jpg", "image/jpeg"), self.photo("two.webp", "image/webp")]

        repository.create_listing(UID, values=dict(VALUES), photos=photos)

        names = [call.args[0] for call in container.return_value.get_blob_client.call_args_list]
        self.assertEqual(len(names), 2)
        self.assertNotEqual(names[0], names[1])
        for name in names:
            self.assertRegex(name, rf"^{UID}/[0-9a-f]{{32}}$")
        for blob, photo in zip(blobs, photos):
            blob.upload_blob.assert_called_once()
            call = blob.upload_blob.call_args
            self.assertIs(call.args[0], photo)
            self.assertEqual(call.kwargs["length"], photo.size)
            self.assertIsInstance(call.kwargs["content_settings"], ContentSettings)
            self.assertEqual(call.kwargs["content_settings"].content_type, photo.content_type)
        written = self.reference(client).create.call_args.args[0]
        self.assertEqual(written["photos"], ["https://example/0", "https://example/1"])

    def test_storage_failure_deletes_already_uploaded_photos(self, container, client, get_app):
        first_blob = MagicMock()
        second_blob = MagicMock()
        second_blob.upload_blob.side_effect = OSError("storage failure")
        container.return_value.get_blob_client.side_effect = [first_blob, second_blob]
        photos = [self.photo("one.jpg"), self.photo("two.jpg")]

        with self.assertRaises(OSError):
            repository.create_listing(UID, values=dict(VALUES), photos=photos)

        first_blob.delete_blob.assert_called_once_with()
        self.reference(client).create.assert_not_called()

    def test_firestore_failure_deletes_uploaded_photos(self, container, client, get_app):
        reference = self.reference(client)
        reference.create.side_effect = ServiceUnavailable("caído")
        reference.get.return_value.exists = False
        blob = self.blob(container)

        with self.assertRaises(ServiceUnavailable):
            repository.create_listing(UID, values=dict(VALUES), photos=[self.photo()])

        blob.delete_blob.assert_called_once_with()

    def test_cleanup_failure_is_logged_by_class_name_only(self, container, client, get_app):
        reference = self.reference(client)
        reference.create.side_effect = ServiceUnavailable("caído")
        reference.get.return_value.exists = False
        blob = self.blob(container)
        blob.delete_blob.side_effect = OSError("detalle-interno-del-error")

        with self.assertLogs("accounts.repository", level="ERROR") as logs, self.assertRaises(ServiceUnavailable):
            repository.create_listing(UID, values=dict(VALUES), photos=[self.photo()])

        self.assertIn("OSError", logs.output[0])
        self.assertNotIn("detalle-interno-del-error", logs.output[0])

    def test_firestore_confirmation_error_does_not_delete_confirmed_listing_photos(
        self, container, client, get_app
    ):
        reference = self.reference(client)
        reference.id = "listing-ambiguous"
        reference.create.side_effect = OSError("respuesta perdida")
        reference.get.return_value.exists = True
        blob = self.blob(container)

        result = repository.create_listing(UID, values=dict(VALUES), photos=[self.photo()])

        self.assertEqual(result, {"id": "listing-ambiguous"})
        blob.delete_blob.assert_not_called()

    def test_firestore_probe_failure_preserves_photos_for_reconciliation(
        self, container, client, get_app
    ):
        reference = self.reference(client)
        reference.id = "listing-unknown"
        reference.create.side_effect = OSError("respuesta perdida")
        reference.get.side_effect = OSError("Firestore sigue caído")
        blob = self.blob(container)

        with self.assertRaises(OSError):
            repository.create_listing(UID, values=dict(VALUES), photos=[self.photo()])

        blob.delete_blob.assert_not_called()


@patch("accounts.repository.get_app")
@patch("accounts.repository.firestore.client")
class CreateListingWithoutStorageConfigTests(SimpleTestCase):
    def test_missing_connection_string_fails_before_any_write(self, client, get_app):
        env = {key: value for key, value in os.environ.items() if not key.startswith("AZURE_STORAGE_")}
        with patch.dict(os.environ, env, clear=True), patch.object(azure_storage, "_container", None):
            with self.assertLogs("accounts.azure_storage", level="ERROR"):
                with self.assertRaises(StorageConfigError) as raised:
                    repository.create_listing(
                        UID, values=dict(VALUES),
                        photos=[SimpleUploadedFile("one.jpg", b"data", content_type="image/jpeg")],
                    )
        self.assertIn("AZURE_STORAGE_CONNECTION_STRING", str(raised.exception))
        client.return_value.collection.return_value.document.return_value.create.assert_not_called()
