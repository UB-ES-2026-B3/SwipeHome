from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase
from firebase_admin import firestore
from google.api_core.exceptions import AlreadyExists, ServiceUnavailable

from . import repository

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


@patch("accounts.repository.get_app")
@patch("accounts.repository.firestore.client")
@patch("accounts.repository._storage_bucket")
class CreateListingTests(SimpleTestCase):
    def test_writes_listing_to_firestore_with_verified_seller(self, bucket, client, get_app):
        reference = client.return_value.collection.return_value.document.return_value
        reference.id = "listing-123"
        blob = bucket.return_value.blob.return_value
        bucket.return_value.name = "swipehome-a51d7.firebasestorage.app"
        values = {
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
        photos = [SimpleUploadedFile("piso.jpg", b"data", content_type="image/jpeg")]

        result = repository.create_listing(UID, values=values, photos=photos)

        client.assert_called_once_with(app=get_app.return_value)
        client.return_value.collection.assert_called_once_with("listings")
        reference.create.assert_called_once()
        written = reference.create.call_args.args[0]
        self.assertEqual(written["seller_uid"], UID)
        self.assertEqual(written["price_cents"], 95050)
        self.assertEqual(written["surface_hundredths"], 6550)
        self.assertTrue(written["photos"][0].startswith(
            "https://firebasestorage.googleapis.com/v0/b/"
        ))
        blob.patch.assert_called_once()
        self.assertEqual(result["id"], "listing-123")

    def test_storage_failure_deletes_already_uploaded_photos(self, bucket, client, get_app):
        first_blob = MagicMock()
        second_blob = MagicMock()
        second_blob.upload_from_file.side_effect = OSError("storage failure")
        bucket.return_value.blob.side_effect = [first_blob, second_blob]
        values = {
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
        photos = [
            SimpleUploadedFile("one.jpg", b"one", content_type="image/jpeg"),
            SimpleUploadedFile("two.jpg", b"two", content_type="image/jpeg"),
        ]

        with self.assertRaises(OSError):
            repository.create_listing(UID, values=values, photos=photos)

        first_blob.delete.assert_called_once_with()
        client.return_value.collection.return_value.document.return_value.create.assert_not_called()
