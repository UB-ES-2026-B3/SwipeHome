from io import BytesIO
from types import SimpleNamespace
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase
from PIL import Image

from accounts.authentication import AuthenticationFailed
from accounts import repository
from accounts.repository import get_seller_listings


def image_file(name, image_format, content_type):
    output = BytesIO()
    Image.new("RGB", (2, 2), color="white").save(output, format=image_format)
    return SimpleUploadedFile(name, output.getvalue(), content_type=content_type)


def jpeg(name="one.jpg"):
    return image_file(name, "JPEG", "image/jpeg")


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
                return_value={"id": "listing-1"},
            )
        )
        self.get_seller_listings = self.enterContext(
            patch(
                "properties.views.repository.get_seller_listings",
                return_value=[{"id": "listing-1", "title": "Piso luminoso"}],
            )
        )

    def publish(self, values=None, photos=None):
        data = dict(VALID if values is None else values)
        data["photos"] = [jpeg()] if photos is None else photos
        return self.client.post("/api/inmuebles", data=data)

    def test_valid_publication_with_one_photo_uses_verified_seller(self):
        response = self.publish()

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json(), {"id": "listing-1"})
        self.create_listing.assert_called_once()
        self.assertEqual(self.create_listing.call_args.args, (self.uid,))
        self.assertEqual(self.create_listing.call_args.kwargs["photos"][0].name, "one.jpg")

    def test_multiple_photos_preserve_order_and_listing_owner_cannot_be_spoofed(self):
        photos = [jpeg("first.jpg"), jpeg("second.jpg"), jpeg("third.jpg")]
        response = self.publish(
            values={
                **VALID,
                "seller_uid": "attacker-uid",
                "owner_uid": "another-attacker",
                "uid": "untrusted-client-uid",
            },
            photos=photos,
        )

        self.assertEqual(response.status_code, 201)
        self.create_listing.assert_called_once()
        self.assertEqual(self.create_listing.call_args.args, (self.uid,))
        self.assertNotIn("seller_uid", self.create_listing.call_args.kwargs["values"])
        self.assertEqual(
            [photo.name for photo in self.create_listing.call_args.kwargs["photos"]],
            ["first.jpg", "second.jpg", "third.jpg"],
        )

    def test_get_returns_only_the_authenticated_sellers_listings(self):
        response = self.client.get("/api/inmuebles")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"properties": [{"id": "listing-1", "title": "Piso luminoso"}]})
        self.get_seller_listings.assert_called_once_with(self.uid)

    def test_seller_listings_ignore_published_records_without_an_owner(self):
        with patch(
            "accounts.repository._listings",
        ):
            snapshots = [
                SimpleNamespace(id="legacy-listing", to_dict=lambda: {"published": True}),
                SimpleNamespace(
                    id="listing-1",
                    to_dict=lambda: {
                        "published": True,
                        "seller_uid": self.uid,
                        "title": "Piso luminoso",
                        "photos": [],
                    },
                ),
            ]
            repository._listings.return_value.stream.return_value = snapshots
            self.assertEqual(get_seller_listings(self.uid)[0]["title"], "Piso luminoso")

    def test_anonymous_user_is_rejected_before_body_validation(self):
        self.uid_from_request.side_effect = AuthenticationFailed("missing")

        response = self.client.post("/api/inmuebles", data=b"{", content_type="application/json")

        self.assertEqual(response.status_code, 401)
        self.create_listing.assert_not_called()

    def test_unavailable_token_verification_is_generic(self):
        from accounts.authentication import TokenVerificationUnavailable

        self.uid_from_request.side_effect = TokenVerificationUnavailable("private provider details")
        with self.assertLogs("properties.views", level="ERROR") as logs:
            response = self.publish()

        self.assertEqual(response.status_code, 500)
        self.assert_safe_error(response, "private provider details")
        self.assertNotIn("private provider details", " ".join(logs.output))
        self.create_listing.assert_not_called()

    def test_buyer_is_rejected(self):
        self.profile.return_value["role"] = "BUYER"

        response = self.publish()

        self.assertEqual(response.status_code, 403)
        self.create_listing.assert_not_called()

    def test_every_required_property_field_is_rejected_when_missing(self):
        for field in VALID:
            with self.subTest(field=field):
                values = dict(VALID)
                del values[field]
                response = self.publish(values=values)

                self.assertEqual(response.status_code, 400)
                self.assertIn(field, response.json()["errors"])
                self.create_listing.assert_not_called()

    def test_empty_text_and_out_of_range_values_are_rejected(self):
        cases = {
            "title": ["", "   "],
            "street": ["", "   "],
            "city": ["", "   "],
            "postal_code": ["", "   "],
            "description": ["", "   "],
            "price": ["0", "-1", "NaN", "1.234", "10000000000"],
            "surface": ["0", "-1", "Infinity", "1.234", "10000000000"],
            "bedrooms": ["-1", "1.5", "abc"],
            "bathrooms": ["0", "-1", "1.5", "abc"],
            "people": ["0", "-1", "1.5", "abc"],
            "shared_accommodation": ["", "maybe", "true"],
        }
        for field, invalid_values in cases.items():
            for value in invalid_values:
                with self.subTest(field=field, value=value):
                    response = self.publish(values={**VALID, field: value})

                    self.assertEqual(response.status_code, 400)
                    self.assertIn(field, response.json()["errors"])
                    self.create_listing.assert_not_called()

    def test_invalid_json_and_wrong_content_type_are_rejected(self):
        for content_type, body in (
            ("application/json", '{"title": 42, "people": []}'),
            ("application/json", "{"),
            ("text/plain", "title=Piso"),
        ):
            with self.subTest(content_type=content_type, body=body):
                response = self.client.post(
                    "/api/inmuebles",
                    data=body,
                    content_type=content_type,
                    HTTP_AUTHORIZATION="Bearer test-token",
                )

                self.assertEqual(response.status_code, 400)
                self.create_listing.assert_not_called()

    def test_file_cannot_be_submitted_instead_of_a_text_field(self):
        response = self.publish(values={**VALID, "title": jpeg("title.jpg")})

        self.assertEqual(response.status_code, 400)
        self.assertIn("title", response.json()["errors"])
        self.create_listing.assert_not_called()

    def test_no_photos_returns_bad_request_without_creating_listing(self):
        response = self.publish(photos=[])

        self.assertEqual(response.status_code, 400)
        self.assertIn("photos", response.json()["errors"])
        self.create_listing.assert_not_called()

    def test_contradictory_aliases_are_rejected(self):
        response = self.publish(values={**VALID, "title": "Piso A", "titulo": "Piso B"})

        self.assertEqual(response.status_code, 400)
        self.assertIn("title", response.json()["errors"])
        self.create_listing.assert_not_called()

    def test_one_or_multiple_people_and_both_shared_accommodation_options(self):
        for people, shared, expected in (
            ("1", "No", False),
            ("1", "Sí", True),
            ("4", "No", False),
            ("4", "Sí", True),
        ):
            with self.subTest(people=people, shared=shared):
                response = self.publish(
                    values={**VALID, "people": people, "shared_accommodation": shared}
                )

                self.assertEqual(response.status_code, 201)
                self.assertEqual(
                    self.create_listing.call_args.kwargs["values"]["people"],
                    int(people),
                )
                self.assertIs(
                    self.create_listing.call_args.kwargs["values"]["shared_accommodation"],
                    expected,
                )
                self.create_listing.reset_mock()

    def test_jpeg_png_and_webp_are_accepted(self):
        photos = [
            jpeg("one.jpg"),
            image_file("two.png", "PNG", "image/png"),
            image_file("three.webp", "WEBP", "image/webp"),
        ]
        response = self.publish(photos=photos)

        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            [photo.name for photo in self.create_listing.call_args.kwargs["photos"]],
            ["one.jpg", "two.png", "three.webp"],
        )

    def test_unsupported_format_mime_mismatch_and_non_image_are_rejected(self):
        invalid_photos = (
            image_file("animated.gif", "GIF", "image/gif"),
            SimpleUploadedFile("fake.jpg", b"not an image", content_type="image/jpeg"),
            SimpleUploadedFile("wrong-mime.jpg", jpeg().read(), content_type="image/png"),
        )
        for photo in invalid_photos:
            with self.subTest(name=photo.name, content_type=photo.content_type):
                self.create_listing.reset_mock()
                response = self.publish(photos=[photo])

                self.assertEqual(response.status_code, 400)
                self.assertIn("photos[0]", response.json()["errors"])
                self.create_listing.assert_not_called()

    def test_photo_count_limit_accepts_ten_and_rejects_eleven(self):
        response = self.publish(photos=[jpeg(f"{index}.jpg") for index in range(10)])

        self.assertEqual(response.status_code, 201)
        self.assertEqual(len(self.create_listing.call_args.kwargs["photos"]), 10)
        self.create_listing.reset_mock()

        response = self.publish(photos=[jpeg(f"{index}.jpg") for index in range(11)])

        self.assertEqual(response.status_code, 400)
        self.assertIn("photos", response.json()["errors"])
        self.create_listing.assert_not_called()

    def test_photo_size_limit_accepts_five_mib_and_rejects_larger_file(self):
        valid_jpeg = jpeg()
        image_bytes = valid_jpeg.read()
        max_size = 5 * 1024 * 1024
        boundary_data = image_bytes + b"\x00" * (max_size - len(image_bytes))

        response = self.publish(
            photos=[SimpleUploadedFile("boundary.jpg", boundary_data, content_type="image/jpeg")]
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            self.create_listing.call_args.kwargs["photos"][0].size,
            max_size,
        )
        self.create_listing.reset_mock()

        response = self.publish(
            photos=[
                SimpleUploadedFile(
                    "too-large.jpg",
                    boundary_data + b"\x00",
                    content_type="image/jpeg",
                )
            ]
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("photos[0]", response.json()["errors"])
        self.create_listing.assert_not_called()

    def test_repository_failure_returns_generic_response_without_internal_details(self):
        secret = "private-storage-bucket-or-credential"
        self.create_listing.side_effect = RuntimeError(secret)

        with self.assertLogs("properties.views", level="ERROR") as logs:
            response = self.publish()

        self.assertEqual(response.status_code, 500)
        self.assert_safe_error(response, secret)
        self.assertNotIn(secret, " ".join(logs.output))

    def assert_safe_error(self, response, secret):
        body = response.content.decode()
        self.assertNotIn(secret, body)
        self.assertNotIn("Traceback", body)
        self.assertNotIn("google.api_core", body)
        self.assertNotIn("firebase_admin", body)

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
