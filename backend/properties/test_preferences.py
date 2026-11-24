"""US8/US8.5: validación, contratos HTTP y errores sin proveedores remotos."""
import json
from unittest.mock import patch
from django.test import Client, SimpleTestCase
from firebase_admin import auth
from accounts import repository
from properties.preferences import FIELDS, fingerprint, matches_preferences, validate_preferences
from properties.test_discovery import listing


class PreferenceValidationTests(SimpleTestCase):
    def valid(self, body):
        values, errors = validate_preferences(body)
        self.assertEqual(errors, {}, body)
        return values

    def test_empty_null_and_canonical_equivalence(self):
        empty = self.valid({})
        self.assertEqual(empty, dict.fromkeys(FIELDS))
        self.assertEqual(self.valid(dict.fromkeys(FIELDS)), empty)
        self.assertEqual(self.valid({"city": "  ", "postal_code": ""}), empty)
        self.assertEqual(self.valid({"city": " Barcelona ", "postal_code": " 08001 "})["postal_code"], "08001")
        self.assertEqual(fingerprint(self.valid({"min_price": "0", "max_area": "65.5"})),
                         fingerprint(self.valid({"min_price": "0.00", "max_area": "65.50"})))
        self.assertNotEqual(fingerprint(empty), fingerprint(self.valid({"is_shared": False})))
        self.assertNotEqual(fingerprint(empty), fingerprint(self.valid({"bedrooms": 0})))
        large = self.valid({"max_price": "9" * 97})
        self.assertEqual(self.valid(large), large)
        self.assertIn("max_price", validate_preferences({"max_price": "9" * 98})[1])

    def test_all_invalid_types_and_nonfinite_values(self):
        for body in ([], True, 1, "", None):
            self.assertIn("body", validate_preferences(body)[1])
        for field in FIELDS:
            invalid = ([True, False, 1, [], {}, "", "NaN", "Infinity", "-Infinity", "1e999999", "1e-999999", "1_000", "-1", 1.1]
                       if field.startswith(("min_price", "max_price", "min_area", "max_area")) else
                       [True, False, -1, 1.1, "1", [], {}, 2**63] if field in ("bedrooms", "min_bathrooms", "people_offered") else
                       [0, 1, "false", [], {}] if field == "is_shared" else [0, False, [], {}])
            for value in invalid:
                with self.subTest(field=field, value=value):
                    self.assertIn(field, validate_preferences({field: value})[1])
        for field in ("uid", "buyer_id", "email", "role", "unknown"):
            self.assertIn(field, validate_preferences({field: "other"})[1])
        for field in ("min_bathrooms", "people_offered"):
            self.assertIn(field, validate_preferences({field: 0})[1])

    def test_decimal_limits_precision_and_ranges(self):
        self.valid({"min_price": "0", "max_price": "0.01", "min_area": "0.01"})
        self.valid({"max_price": "999999999999999999999999999999999.99"})
        for field in ("max_price", "min_area", "max_area"):
            self.assertIn(field, validate_preferences({field: "0"})[1])
        for low, high in (("min_price", "max_price"), ("min_area", "max_area")):
            self.valid({low: "65.50"})
            self.valid({high: "65.50"})
            self.valid({low: "65.50", high: "65.50"})
            self.assertIn(high, validate_preferences({low: "65.51", high: "65.50"})[1])
            for field in (low, high):
                for value in ("0.001", "1.000"):
                    self.assertIn(field, validate_preferences({field: value})[1])

    def test_individual_filters_and_all_filters_and_boundaries(self):
        cases = [({"city": "Barcelona"}, {"city": "Madrid"}),
                 ({"postal_code": "08001"}, {"postal_code": "08002"}),
                 ({"min_price": "950.50"}, {"price_cents": 95049}),
                 ({"max_price": "950.50"}, {"price_cents": 95051}),
                 ({"min_area": "65.50"}, {"surface_hundredths": 6549}),
                 ({"max_area": "65.50"}, {"surface_hundredths": 6551}),
                 ({"bedrooms": 2}, {"bedrooms": 3}),
                 ({"min_bathrooms": 1}, {"bathrooms": 0}),
                 ({"people_offered": 3}, {"people": 2}),
                 ({"is_shared": False}, {"shared_accommodation": True})]
        all_values = {}
        for body, change in cases:
            values = self.valid(body)
            self.assertTrue(matches_preferences(listing(), values), body)
            self.assertFalse(matches_preferences(listing(**change), values), body)
            all_values.update(body)
        self.assertTrue(matches_preferences(listing(), self.valid(all_values)))
        self.assertFalse(matches_preferences(listing(city="Madrid"), self.valid(all_values)))
        self.assertTrue(matches_preferences(listing(bathrooms=2), self.valid({"min_bathrooms": 1})))
        self.assertTrue(matches_preferences(listing(bedrooms=0), self.valid({"bedrooms": 0})))
        self.assertFalse(matches_preferences(listing(), self.valid({"bedrooms": 0})))
        self.assertTrue(matches_preferences(listing(), self.valid({"bedrooms": None, "is_shared": None})))
        self.assertTrue(matches_preferences(listing(shared_accommodation=True), self.valid({"is_shared": True, "people_offered": 3})))
        self.assertTrue(matches_preferences(listing(postal_code="AB 01"), self.valid({"postal_code": " AB 01 "})))


class PreferenceApiTests(SimpleTestCase):
    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)
        self.enterContext(patch("accounts.authentication.get_app"))
        self.verify = self.enterContext(patch("accounts.authentication.auth.verify_id_token", return_value={"uid": "buyer", "auth_time": 100}))
        self.revoked = self.enterContext(patch("accounts.repository.is_session_revoked", return_value=False))
        self.profile = self.enterContext(patch("accounts.repository.get_user_profile", return_value={"role": "BUYER"}))
        self.empty = validate_preferences({})[0]
        self.read = self.enterContext(patch("accounts.repository.get_search_preferences", return_value=self.empty))
        self.save = self.enterContext(patch("accounts.repository.save_search_preferences", side_effect=lambda uid, values: values))
        self.delete = self.enterContext(patch("accounts.repository.delete_search_preferences"))
        self.cities = self.enterContext(patch("accounts.repository.get_filter_cities", return_value=["Barcelona"]))
        self.pending = self.enterContext(patch("accounts.repository.get_pending_listings", return_value=[]))

    def send(self, method="get", body=None, token="token", path="/api/exploracion/filtros"):
        kwargs = {} if token is None else {"HTTP_AUTHORIZATION": "Bearer " + token}
        if method == "put":
            kwargs.update(data=json.dumps(body), content_type="application/json")
        return getattr(self.client, method)(path, **kwargs)

    def test_permissions_every_endpoint_and_credential_failure(self):
        operations = [("get", "/api/exploracion/filtros"), ("put", "/api/exploracion/filtros"),
                      ("delete", "/api/exploracion/filtros"), ("get", "/api/inmuebles/opciones-filtro"),
                      ("get", "/api/inmuebles/explorar")]
        for method, path in operations:
            self.assertEqual(self.send(method, {}, None, path).status_code, 401)
            self.profile.return_value = {"role": "SELLER"}
            self.assertEqual(self.send(method, {}, path=path).status_code, 403)
            self.profile.return_value = {"role": "BUYER"}
            for error in (auth.InvalidIdTokenError("bad"), auth.ExpiredIdTokenError("bad", None), auth.RevokedIdTokenError("bad")):
                self.verify.side_effect = error
                self.assertEqual(self.send(method, {}, path=path).status_code, 401)
            self.verify.side_effect = None
            self.revoked.return_value = True
            self.assertEqual(self.send(method, {}, path=path).status_code, 401)
            self.revoked.return_value = False
            expected = 204 if method == "delete" else 200
            self.assertEqual(self.send(method, {}, path=path).status_code, expected)
            self.verify.side_effect = RuntimeError("infrastructure")
            self.assertEqual(self.send(method, {}, path=path).status_code, 500)
            self.verify.side_effect = None

    def test_identity_queries_unknown_fields_and_invalid_json(self):
        for field in ("uid", "user_id", "buyer_id", "email", "role"):
            self.assertEqual(self.send("put", {field: "other"}).status_code, 400)
            for path in ("/api/exploracion/filtros", "/api/inmuebles/opciones-filtro", "/api/inmuebles/explorar"):
                self.assertEqual(self.send(path=path + "?" + field + "=other").status_code, 400)
        for raw in (b"{", b"", b"\xff", b'{"min_price":NaN}', b'{"min_price":Infinity}', b'{"bedrooms":NaN}'):
            response = self.client.put("/api/exploracion/filtros", raw, content_type="application/json", HTTP_AUTHORIZATION="Bearer token")
            self.assertEqual(response.status_code, 400)
        self.save.assert_not_called()
        self.assertEqual(self.send("put", {"bedrooms": 0, "is_shared": False}).status_code, 200)
        self.save.assert_called_once_with("buyer", validate_preferences({"bedrooms": 0, "is_shared": False})[0])
        self.assertIn("no-store", self.send()["Cache-Control"])

    def test_read_write_failures_and_successful_save_then_explore_failure(self):
        self.read.side_effect = RuntimeError("private detail")
        self.assertEqual(self.send().status_code, 500)
        self.read.side_effect = None
        self.save.side_effect = RuntimeError("private detail")
        self.assertEqual(self.send("put", {}).status_code, 500)
        self.delete.side_effect = RuntimeError("private detail")
        self.assertEqual(self.send("delete").status_code, 500)
        self.delete.side_effect = None
        self.save.side_effect = lambda uid, values: values
        self.assertEqual(self.send("put", {"min_price": "0"}).status_code, 200)
        self.pending.side_effect = RuntimeError("private detail")
        self.assertEqual(self.send(path="/api/inmuebles/explorar").status_code, 500)
        self.pending.side_effect = None
        self.assertEqual(self.send(path="/api/inmuebles/explorar").json(), {"items": [], "next_cursor": None})
        self.cities.side_effect = RuntimeError("private detail")
        self.assertEqual(self.send(path="/api/inmuebles/opciones-filtro").status_code, 500)
