import json
from types import SimpleNamespace
from unittest.mock import patch

from django.test import Client, SimpleTestCase
from firebase_admin import auth
from google.api_core.exceptions import ServiceUnavailable

from .firebase import FirebaseConfigError

# SimpleTestCase: cualquier acceso al ORM hace fallar el test. Las vistas nuevas
# no deben tocar la base de datos de Django.

VALID = {
    "name": "Ana García",
    "email": "ana@example.com",
    "password": "  Contraseña íntegra 2026!  ",
    "role": "BUYER",
}
UID = "uid-de-prueba-123"
TOKEN = "eyJhbGciOiJSUzI1NiJ9.token-secreto-de-prueba.firma"


def profile_from(uid, *, name, email, role):
    return {"uid": uid, "name": name, "email": email, "role": role}


class FirebaseMocks:
    """Simula firebase_admin.auth y el repositorio; nunca se llama a Firebase de verdad."""

    def setUp(self):
        self.get_app = self.start(patch("accounts.views.get_app"))
        self.create_user = self.start(patch("accounts.views.auth.create_user", return_value=SimpleNamespace(uid=UID)))
        self.delete_user = self.start(patch("accounts.views.auth.delete_user"))
        self.create_profile = self.start(patch("accounts.views.repository.create_user_profile", side_effect=profile_from))
        self.get_profile = self.start(patch("accounts.views.repository.get_user_profile"))
        self.start(patch("accounts.authentication.get_app"))
        self.revoked_lookup = self.start(patch("accounts.repository.is_session_revoked", return_value=False))
        self.verify = self.start(patch("accounts.authentication.auth.verify_id_token", return_value={"uid": UID, "auth_time": 100}))

    def start(self, patcher):
        mock = patcher.start()
        self.addCleanup(patcher.stop)
        return mock

    def assert_safe(self, response, logs=()):
        text = response.content.decode() + "\n".join(logs)
        for secret in (VALID["password"], TOKEN, "Traceback", "secret_backend_detail"):
            self.assertNotIn(secret, text)
        self.assertNotIn("sessionid", response.cookies)
        self.assertNotIn("csrftoken", response.cookies)


class RegisterTests(FirebaseMocks, SimpleTestCase):
    def post(self, data, client=None, **kwargs):
        return (client or self.client).post(
            "/api/auth/register", data=json.dumps(data), content_type="application/json", **kwargs
        )

    def test_valid_roles_create_user_and_profile(self):
        for role in ("BUYER", "SELLER"):
            with self.subTest(role=role):
                email = role.lower() + "@example.com"
                response = self.post({**VALID, "role": role, "email": email})
                self.assertEqual(response.status_code, 201)
                self.assertEqual(response.json(), {"uid": UID, "name": VALID["name"], "email": email, "role": role})
                self.create_user.assert_called_with(email=email, password=VALID["password"], display_name=VALID["name"], app=self.get_app.return_value)
                self.create_profile.assert_called_with(UID, name=VALID["name"], email=email, role=role)
                self.assertNotIn("Location", response)
                self.assert_safe(response)
        self.delete_user.assert_not_called()

    def test_exact_endpoint_and_methods(self):
        self.assertEqual(self.client.post("/api/auth/register/").status_code, 404)
        # Ya no existe el GET que servía el token CSRF.
        self.assertEqual(self.client.get("/api/auth/register").status_code, 405)
        self.assertEqual(self.client.post("/api/auth/login", data=json.dumps(VALID), content_type="application/json").status_code, 404)

    def test_works_without_csrf_token(self):
        response = self.post(VALID, client=Client(enforce_csrf_checks=True))
        self.assertEqual(response.status_code, 201)

    def test_required_fields_and_strict_types(self):
        for field in VALID:
            missing = dict(VALID)
            del missing[field]
            with self.subTest(field=field, value="absent"):
                self.assertEqual(self.post(missing).status_code, 400)
            for value in (None, 42, 3.14, True, False, [], {}, ["text"]):
                with self.subTest(field=field, value=value):
                    response = self.post({**VALID, field: value})
                    self.assertEqual(response.status_code, 400)
                    self.assertIn(field, response.json()["errors"])
                    self.assert_safe(response)
        self.create_user.assert_not_called()

    def test_invalid_form_rules(self):
        cases = {
            "name": ["", " ", " a ", "x" * 81],
            "email": ["", "not-an-email", "a b@example.com", "a@exa mple.com", "a\\tb@example.com",
                      "a" * 64 + "@" + "b" * 63 + "." + "c" * 63 + "." + "d" * 63 + ".com"],
            "password": ["", "x" * 14, "x" * 129],
            "role": ["", "seller", "buyer", "ADMIN", " SELLER", "BUYER "],
        }
        for field, values in cases.items():
            for value in values:
                with self.subTest(field=field, length=len(value)):
                    response = self.post({**VALID, field: value})
                    self.assertEqual(response.status_code, 400)
                    self.assertIn(field, response.json()["errors"])
                    self.assert_safe(response)
        self.create_user.assert_not_called()

    def test_boundary_lengths_and_unicode_password_are_sent_untouched(self):
        for length, name in ((15, " ab "), (128, "ñ" * 80)):
            with self.subTest(length=length):
                password = "A1!" + "🙂" * (length - 3)
                response = self.post({**VALID, "name": name, "password": password, "email": f"a{length}@example.com"})
                self.assertEqual(response.status_code, 201)
                self.assertEqual(self.create_user.call_args.kwargs["password"], password)
                self.assertEqual(self.create_profile.call_args.kwargs["name"], name.strip())

    def test_password_composed_only_of_spaces_is_preserved(self):
        self.assertEqual(self.post({**VALID, "password": " " * 15}).status_code, 400)
        self.create_user.assert_not_called()

    def test_email_254_boundary(self):
        email = "a" * 64 + "@" + "b" * 63 + "." + "c" * 63 + "." + "d" * 57 + ".com"
        self.assertEqual(len(email), 254)
        self.assertEqual(self.post({**VALID, "email": email}).status_code, 201)

    def test_email_and_name_are_normalized_before_firebase(self):
        response = self.post({**VALID, "email": "  ANA@Example.COM  ", "name": "  Ana García  "})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(self.create_user.call_args.kwargs["email"], "ana@example.com")
        self.create_profile.assert_called_once_with(UID, name="Ana García", email="ana@example.com", role="BUYER")

    def test_malformed_json_and_body_types(self):
        for body in ("{", "null", "[]", "true", "42", '"text"'):
            with self.subTest(body=body):
                response = self.client.post("/api/auth/register", data=body, content_type="application/json")
                self.assertEqual(response.status_code, 400)
                self.assert_safe(response)
        self.assertEqual(self.client.post("/api/auth/register", VALID).status_code, 400)
        self.create_user.assert_not_called()

    def test_duplicate_email_is_409_and_deletes_nothing(self):
        self.create_user.side_effect = auth.EmailAlreadyExistsError("EMAIL_EXISTS", None, None)
        response = self.post(VALID)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json(), {"error": "El email ya está registrado."})
        self.create_profile.assert_not_called()
        # Ese usuario es de otra persona: la acción compensatoria no debe tocarlo.
        self.delete_user.assert_not_called()

    def test_firebase_auth_failure_is_500_without_details(self):
        self.create_user.side_effect = RuntimeError("secret_backend_detail " + VALID["password"])
        with self.assertLogs("accounts.views", level="ERROR") as logs:
            response = self.post(VALID)
        self.assertEqual(response.status_code, 500)
        self.assert_safe(response, logs.output)
        self.create_profile.assert_not_called()
        self.delete_user.assert_not_called()

    def test_missing_credentials_is_503_with_specific_error(self):
        self.get_app.side_effect = FirebaseConfigError("No hay credenciales de Firebase.")
        with self.assertLogs("accounts.views", level="ERROR"):
            response = self.post(VALID)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.json(),
            {
                "error": (
                    "El servidor no está configurado para crear cuentas. "
                    "Falta la credencial de Firebase en el entorno local."
                )
            },
        )

    def test_firestore_failure_deletes_firebase_user(self):
        self.create_profile.side_effect = ServiceUnavailable("secret_backend_detail")
        with self.assertLogs("accounts.views", level="ERROR") as logs:
            response = self.post(VALID)
        self.assertEqual(response.status_code, 500)
        self.delete_user.assert_called_once_with(UID, app=self.get_app.return_value)
        self.assertIn(UID, "\n".join(logs.output))
        self.assert_safe(response, logs.output)

    def test_failed_compensation_is_logged_with_uid_and_still_500(self):
        self.create_profile.side_effect = ServiceUnavailable("secret_backend_detail")
        self.delete_user.side_effect = RuntimeError("secret_backend_detail")
        with self.assertLogs("accounts.views", level="ERROR") as logs:
            response = self.post(VALID)
        self.assertEqual(response.status_code, 500)
        compensation = [line for line in logs.output if "borrado compensatorio" in line]
        self.assertEqual(len(compensation), 1)
        self.assertIn(UID, compensation[0])
        self.assertTrue(compensation[0].startswith("ERROR:"))
        self.assert_safe(response, logs.output)


class CurrentUserTests(FirebaseMocks, SimpleTestCase):
    def get(self, authorization=f"Bearer {TOKEN}", path="/api/auth/me"):
        headers = {} if authorization is None else {"HTTP_AUTHORIZATION": authorization}
        return self.client.get(path, **headers)

    def test_valid_token_returns_profile_from_firestore(self):
        self.get_profile.return_value = {"uid": UID, "name": "Ana", "email": "ana@example.com", "role": "SELLER"}
        for _ in range(3):
            response = self.get(path="/api/auth/me?uid=otro&role=ADMIN")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), self.get_profile.return_value)
            self.assertIn("no-store", response["Cache-Control"])
            self.assert_safe(response)
        self.assertEqual(self.verify.call_args.args, (TOKEN,))
        # El uid sale del token, nunca de la query.
        self.get_profile.assert_called_with(UID)

    def test_two_tokens_identify_only_their_own_account(self):
        # Equivalente de test_sessions_identify_only_the_account_that_authenticated
        # (US 2.6), con tokens de Firebase en lugar de cookies de sesión.
        ana = {"uid": "uid-ana", "name": "Ana García", "email": "ana@example.com", "role": "BUYER"}
        bea = {"uid": "uid-bea", "name": "Bea Vendedora", "email": "bea@example.com", "role": "SELLER"}
        uid_by_token = {"token-de-ana": ana["uid"], "token-de-bea": bea["uid"]}
        profile_by_uid = {ana["uid"]: ana, bea["uid"]: bea}
        self.verify.side_effect = (
            lambda token, app=None, check_revoked=False, clock_skew_seconds=0:
            {"uid": uid_by_token[token], "auth_time": 100}
        )
        self.get_profile.side_effect = lambda uid: profile_by_uid[uid]
        ana_client, bea_client = Client(), Client()

        # Peticiones intercaladas: cada token recibe solo su perfil.
        for _ in range(2):
            for client, token, profile, other_token in (
                (ana_client, "token-de-ana", ana, "token-de-bea"),
                (bea_client, "token-de-bea", bea, "token-de-ana"),
            ):
                response = client.get("/api/auth/me", HTTP_AUTHORIZATION=f"Bearer {token}")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json(), profile)
                self.assertNotIn(token, response.content.decode())
                self.assertNotIn(other_token, response.content.decode())
                self.assert_safe(response)

        # Ni la query ni el cliente deciden la identidad: solo el token.
        tampered = ana_client.get("/api/auth/me?uid=uid-bea&role=SELLER", HTTP_AUTHORIZATION="Bearer token-de-ana")
        self.assertEqual(tampered.json(), ana)
        swapped = ana_client.get("/api/auth/me", HTTP_AUTHORIZATION="Bearer token-de-bea")
        self.assertEqual(swapped.json(), bea)
        self.assertEqual([c.args[0] for c in self.get_profile.call_args_list].count("uid-bea"), 3)

    def test_unauthenticated_requests_are_401(self):
        failures = {
            "ausente": (None, None),
            "mal formado": ("Basic abc", None),
            "inválido": (f"Bearer {TOKEN}", auth.InvalidIdTokenError(f"Illegal ID token provided: {TOKEN}")),
            "caducado": (f"Bearer {TOKEN}", auth.ExpiredIdTokenError("caducado", None)),
        }
        for case, (header, error) in failures.items():
            with self.subTest(case=case):
                self.verify.side_effect = error
                with self.assertLogs("accounts.authentication", level="INFO") as logs:
                    response = self.get(header)
                self.assertEqual(response.status_code, 401)
                self.assertEqual(response.json(), {"error": "No hay una sesión autenticada."})
                self.assertEqual(response["WWW-Authenticate"], "Bearer")
                self.assertNotIn("Location", response)
                self.assert_safe(response, logs.output)
        self.get_profile.assert_not_called()

    def test_valid_token_without_profile_is_404_logged_as_error(self):
        self.get_profile.return_value = None
        with self.assertLogs("accounts.views", level="ERROR") as logs:
            response = self.get()
        self.assertEqual(response.status_code, 404)
        # Distinto del 401: el frontend muestra un error de cuenta incompleta.
        self.assertNotEqual(response.json()["error"], "No hay una sesión autenticada.")
        self.assertEqual(len(logs.output), 1)
        self.assertTrue(logs.output[0].startswith("ERROR:"))
        self.assertIn(UID, logs.output[0])
        self.assert_safe(response, logs.output)

    def test_server_failures_are_500_never_401(self):
        failures = {
            "certificados": ("verify", auth.CertificateFetchError("sin red", None)),
            "credencial": ("verify", FirebaseConfigError("No hay credenciales de Firebase.")),
            "firestore": ("profile", ServiceUnavailable("secret_backend_detail")),
        }
        for case, (where, error) in failures.items():
            with self.subTest(case=case):
                self.verify.side_effect = error if where == "verify" else None
                self.get_profile.side_effect = error if where == "profile" else None
                # "accounts" y no la raíz: LOGGING no propaga sus registros hacia arriba.
                with self.assertLogs("accounts", level="ERROR") as logs:
                    response = self.get()
                self.assertTrue(any(line.startswith("ERROR:accounts.views:") for line in logs.output))
                self.assertEqual(response.status_code, 500)
                self.assertNotIn("WWW-Authenticate", response)
                self.assert_safe(response, logs.output)

    def test_exact_endpoint_and_methods(self):
        self.assertEqual(self.get(path="/api/auth/me/").status_code, 404)
        self.assertEqual(self.client.post("/api/auth/me", HTTP_AUTHORIZATION=f"Bearer {TOKEN}").status_code, 405)
