from decimal import Decimal
from io import BytesIO
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from accounts.models import User

from .models import Property, PropertyPhoto


def jpeg(name="one.jpg", content=b"\xff\xd8\xff\xe0valid\xff\xd9"):
    return SimpleUploadedFile(name, content, content_type="image/jpeg")


def png(name="one.png"):
    return SimpleUploadedFile(
        name,
        b"\x89PNG\r\n\x1a\n" + b"data" * 4 + b"IEND",
        content_type="image/png",
    )


class PropertyPublicationTests(TestCase):
    values = {
        "title": "Piso luminoso",
        "street": "Calle Mayor 1",
        "city": "Barcelona",
        "postal_code": "08001",
        "description": "Una descripción válida",
        "price": "950.50",
        "surface": "65.5",
        "bedrooms": "2",
        "bathrooms": "1",
        "people": "3",
        "shared_accommodation": "No",
    }

    def setUp(self):
        self.seller = User.objects.create_user(
            email="seller@example.com",
            password="a secure password",
            name="Seller",
            role="SELLER",
        )
        self.buyer = User.objects.create_user(
            email="buyer@example.com",
            password="a secure password",
            name="Buyer",
            role="BUYER",
        )

    def publish(self, user=None, photos=None, values=None):
        self.client.force_login(user or self.seller)
        data = dict(values or self.values)
        data["photos"] = photos or [jpeg(), png("two.png")]
        return self.client.post("/api/inmuebles", data=data)

    def test_anonymous_and_buyer_are_rejected(self):
        response = self.client.post("/api/inmuebles", data={})
        self.assertEqual(response.status_code, 401)

        response = self.publish(self.buyer)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(Property.objects.count(), 0)

    def test_valid_publication_uses_session_seller_and_preserves_order(self):
        response = self.publish()

        self.assertEqual(response.status_code, 201)
        property_instance = Property.objects.get(pk=response.json()["id"])
        self.assertEqual(property_instance.seller_id, self.seller.pk)
        self.assertTrue(property_instance.published)
        self.assertEqual(property_instance.price, Decimal("950.50"))
        self.assertEqual(list(property_instance.photos.values_list("position", "file")), [
            (0, property_instance.photos.get(position=0).file.name),
            (1, property_instance.photos.get(position=1).file.name),
        ])
        self.assertEqual(property_instance.photos.count(), 2)

    def test_invalid_data_or_images_does_not_create_property(self):
        response = self.publish(values={**self.values, "title": "   "})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Property.objects.count(), 0)

        response = self.publish(photos=[SimpleUploadedFile("fake.jpg", b"not an image", content_type="image/jpeg")])
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Property.objects.count(), 0)

    def test_image_count_and_size_are_enforced(self):
        too_many = [jpeg(str(index) + ".jpg") for index in range(11)]
        self.assertEqual(self.publish(photos=too_many).status_code, 400)

        too_large = SimpleUploadedFile(
            "large.jpg",
            b"\xff\xd8\xff" + b"x" * (5 * 1024 * 1024) + b"\xff\xd9",
            content_type="image/jpeg",
        )
        self.assertEqual(self.publish(photos=[too_large]).status_code, 400)
        self.assertEqual(Property.objects.count(), 0)

    @patch("properties.views.default_storage.save", side_effect=OSError("storage failure"))
    def test_storage_failure_rolls_back_property_and_photo(self, _save):
        response = self.publish(photos=[jpeg()])

        self.assertEqual(response.status_code, 500)
        self.assertEqual(Property.objects.count(), 0)
        self.assertEqual(PropertyPhoto.objects.count(), 0)
