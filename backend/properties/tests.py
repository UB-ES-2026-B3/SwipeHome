import json
from unittest.mock import patch

from django.test import SimpleTestCase

from accounts.authentication import AuthenticationFailed


VALID = {
    "title": "Piso luminoso",
    "street": "Calle Mayor 1",
    "city": "Barcelona",
    "postal_code": "08001",
    "description": "Una descripción válida",
    "price": "950.50",
    "surface": "65.50",
    "bedrooms": 2,
    "bathrooms": 1,
    "people": 3,
    "shared_accommodation": "No",
    "photos": ["https://cdn.example.com/one.jpg", "https://cdn.example.com/two.png"],
}


class PropertyPublicationTests(SimpleTestCase):
    def setUp(self):
        self.uid = "seller-uid"
        self.uid_from_request = self.enterContext(patch("properties.views.uid_from_request", return_value=self.uid))
        self.profile = self.enterContext(patch(
            "properties.views.repository.get_user_profile",
            return_value={"uid": self.uid, "name": "Seller", "email": "seller@example.com", "role": "SELLER"},
        ))
        self.create_listing = self.enterContext(patch(
            "properties.views.repository.create_listing",
            return_value={"id": "listing-1", **VALID, "seller_uid": self.uid, "published": True},
        ))

    def post(self, data=None, content_type="application/json", **headers):
        return self.client.post(
            "/api/inmuebles",
            data=json.dumps(data if data is not None else VALID),
            content_type=content_type,
            **headers,
        )

    def test_valid_publication_uses_verified_seller_and_urls(self):
        response = self.post()

        self.assertEqual(response.status_code, 201)
        self.create_listing.assert_called_once()
        self.assertEqual(self.create_listing.call_args.args, (self.uid,))
        self.assertEqual(self.create_listing.call_args.kwargs["photo_urls"], VALID["photos"])
        self.assertEqual(response.json()["id"], "listing-1")

    def test_anonymous_user_is_rejected(self):
        self.uid_from_request.side_effect = AuthenticationFailed("missing")

        response = self.post()

        self.assertEqual(response.status_code, 401)
        self.create_listing.assert_not_called()

    def test_buyer_is_rejected(self):
        self.profile.return_value["role"] = "BUYER"

        response = self.post()

        self.assertEqual(response.status_code, 403)
        self.create_listing.assert_not_called()

    def test_invalid_fields_and_urls_are_rejected(self):
        response = self.post({**VALID, "title": " ", "photos": ["not-a-url"]})

        self.assertEqual(response.status_code, 400)
        self.assertIn("title", response.json()["errors"])
        self.assertIn("photos[0]", response.json()["errors"])

    def test_aliases_are_supported(self):
        response = self.post({
            "titulo": "Piso",
            "calle": "Calle 1",
            "localidad": "Barcelona",
            "codigoPostal": "08001",
            "descripcion": "Descripción",
            "precio": 950.5,
            "superficie": 65.5,
            "dormitorios": 2,
            "banos": 1,
            "personas": 3,
            "compartido": "Sí",
            "fotografias": ["https://cdn.example.com/one.webp"],
        })

        self.assertEqual(response.status_code, 201)
        self.assertEqual(self.create_listing.call_args.kwargs["values"]["shared_accommodation"], True)

    def test_json_is_required(self):
        response = self.client.post("/api/inmuebles", data={"title": "Piso"})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "Se requiere application/json.")
