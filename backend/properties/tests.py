from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase

from accounts.authentication import AuthenticationFailed


def jpeg(name="one.jpg"):
    return SimpleUploadedFile(name, b"\xff\xd8\xffdata\xff\xd9", content_type="image/jpeg")


VALID = {
    "title": "Piso luminoso",
    "street": "Calle Mayor 1",
    "city": "Barcelona",
    "postal_code": "08001",
    "description": "Una descripción válida",
    "price": "950.50",
    "surface": "65.50",
    "bedrooms": "2",
    "bathrooms": "1",
    "people": "3",
    "shared_accommodation": "No",
}


class PropertyPublicationTests(SimpleTestCase):
    def setUp(self):
        self.uid = "seller-uid"
        self.uid_from_request = self.enterContext(
            patch("properties.views.uid_from_request", return_value=self.uid)
        )
        self.profile = self.enterContext(
            patch(
                "properties.views.repository.get_user_profile",
                return_value={
                    "uid": self.uid,
                    "name": "Seller",
                    "email": "seller@example.com",
                    "role": "SELLER",
                },
            )
        )
        self.create_listing = self.enterContext(
            patch(
                "properties.views.repository.create_listing",
                return_value={"id": "listing-1", "seller_uid": self.uid, "published": True},
            )
        )

    def publish(self, values=None, photos=None):
        data = dict(values or VALID)
        data["photos"] = photos or [jpeg()]
        return self.client.post("/api/inmuebles", data=data)

    def test_valid_publication_uses_verified_seller_and_uploads(self):
        response = self.publish()

        self.assertEqual(response.status_code, 201)
        self.create_listing.assert_called_once()
        self.assertEqual(self.create_listing.call_args.args, (self.uid,))
        self.assertEqual(self.create_listing.call_args.kwargs["photos"][0].name, "one.jpg")

    def test_anonymous_user_is_rejected_before_body_validation(self):
        self.uid_from_request.side_effect = AuthenticationFailed("missing")

        response = self.client.post("/api/inmuebles", data=b"{", content_type="application/json")

        self.assertEqual(response.status_code, 401)
        self.create_listing.assert_not_called()

    def test_buyer_is_rejected(self):
        self.profile.return_value["role"] = "BUYER"

        response = self.publish()

        self.assertEqual(response.status_code, 403)
        self.create_listing.assert_not_called()

    def test_invalid_fields_are_rejected(self):
        response = self.publish(values={**VALID, "title": " "})

        self.assertEqual(response.status_code, 400)
        self.assertIn("title", response.json()["errors"])

    def test_invalid_photo_content_is_rejected(self):
        response = self.publish(
            photos=[SimpleUploadedFile("bad.jpg", b"not an image", content_type="image/jpeg")]
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("photos[0]", response.json()["errors"])

        response = self.publish(
            photos=[SimpleUploadedFile("photo.exe", b"\xff\xd8\xffdata\xff\xd9", content_type="image/jpeg")]
        )
        self.assertEqual(response.status_code, 400)

    def test_photo_count_and_size_are_rejected(self):
        too_many = [jpeg(f"{index}.jpg") for index in range(11)]
        self.assertEqual(self.publish(photos=too_many).status_code, 400)

        too_large = SimpleUploadedFile(
            "large.jpg", b"\xff\xd8\xff" + b"x" * (5 * 1024 * 1024) + b"\xff\xd9",
            content_type="image/jpeg",
        )
        self.assertEqual(self.publish(photos=[too_large]).status_code, 400)

    def test_aliases_are_supported(self):
        response = self.publish(
            values={
                "titulo": "Piso",
                "calle": "Calle 1",
                "localidad": "Barcelona",
                "codigoPostal": "08001",
                "descripcion": "Descripción",
                "precio": "950.50",
                "superficie": "65.50",
                "dormitorios": "2",
                "banos": "1",
                "personas": "3",
                "compartido": "Sí",
            }
        )

        self.assertEqual(response.status_code, 201)
        self.assertTrue(self.create_listing.call_args.kwargs["values"]["shared_accommodation"])

    def test_multipart_is_required(self):
        response = self.client.post("/api/inmuebles", data=b"{}", content_type="application/json")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "Se requiere multipart/form-data.")
