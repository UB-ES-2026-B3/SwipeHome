from unittest.mock import patch

from django.test import RequestFactory, SimpleTestCase
from firebase_admin import auth

from .authentication import (
    EXPIRED,
    INVALID,
    MALFORMED,
    MISSING,
    AuthenticationFailed,
    TokenVerificationUnavailable,
    uid_from_request,
)
from .firebase import FirebaseConfigError

TOKEN = "eyJhbGciOiJSUzI1NiJ9.token-secreto-de-prueba.firma"
UID = "uid-de-prueba-123"


def request_with(authorization=None):
    headers = {} if authorization is None else {"HTTP_AUTHORIZATION": authorization}
    return RequestFactory().get("/api/auth/me", **headers)


@patch("accounts.authentication.get_app")
@patch("accounts.authentication.auth.verify_id_token")
class UidFromRequestTests(SimpleTestCase):
    def setUp(self):
        self.enterContext(patch("accounts.repository.is_session_revoked", return_value=False))

    def assert_fails(self, request, reason):
        with self.assertRaises(AuthenticationFailed) as raised:
            uid_from_request(request)
        self.assertEqual(raised.exception.reason, reason)
        return raised.exception

    def test_valid_token_returns_uid(self, verify, get_app):
        verify.return_value = {"uid": UID, "auth_time": 100, "email": "ana@example.com"}
        self.assertEqual(uid_from_request(request_with(f"Bearer {TOKEN}")), UID)
        verify.assert_called_once_with(
            TOKEN, app=get_app.return_value, check_revoked=True, clock_skew_seconds=10,
        )

    def test_scheme_is_case_insensitive_and_outer_spaces_are_ignored(self, verify, get_app):
        verify.return_value = {"uid": UID, "auth_time": 100}
        self.assertEqual(uid_from_request(request_with(f"  bearer   {TOKEN}  ")), UID)
        verify.assert_called_once_with(
            TOKEN, app=get_app.return_value, check_revoked=True, clock_skew_seconds=10,
        )

    def test_missing_header(self, verify, get_app):
        for header in (None, "", "   "):
            with self.subTest(header=header), self.assertLogs("accounts.authentication", level="INFO"):
                self.assert_fails(request_with(header), MISSING)
        verify.assert_not_called()

    def test_malformed_header(self, verify, get_app):
        for header in ("Bearer", "Bearer   ", f"Basic {TOKEN}", f"Token {TOKEN}", TOKEN, f"Bearer {TOKEN} extra"):
            with self.subTest(header=header), self.assertLogs("accounts.authentication", level="WARNING"):
                self.assert_fails(request_with(header), MALFORMED)
        verify.assert_not_called()

    def test_invalid_token(self, verify, get_app):
        for error in (auth.InvalidIdTokenError("firma incorrecta"), auth.RevokedIdTokenError("revocado")):
            with self.subTest(error=type(error).__name__):
                verify.side_effect = error
                with self.assertLogs("accounts.authentication", level="WARNING"):
                    self.assert_fails(request_with(f"Bearer {TOKEN}"), INVALID)

    def test_expired_token(self, verify, get_app):
        verify.side_effect = auth.ExpiredIdTokenError("caducado", None)
        self.assert_fails(request_with(f"Bearer {TOKEN}"), EXPIRED)

    def test_reasons_are_logged_differently(self, verify, get_app):
        cases = [
            (None, None, MISSING),
            ("Basic x", None, MALFORMED),
            (f"Bearer {TOKEN}", auth.InvalidIdTokenError("mal"), INVALID),
            (f"Bearer {TOKEN}", auth.ExpiredIdTokenError("caducado", None), EXPIRED),
        ]
        messages = set()
        for header, error, reason in cases:
            verify.side_effect = error
            with self.assertLogs("accounts.authentication", level="INFO") as logs:
                self.assert_fails(request_with(header), reason)
            messages.add(logs.output[0])
        self.assertEqual(len(messages), len(cases))

    def test_token_never_appears_in_logs(self, verify, get_app):
        # Algunas excepciones reales de firebase_admin incluyen el token en su mensaje.
        errors = (
            auth.InvalidIdTokenError(f"Illegal ID token provided: {TOKEN}"),
            auth.ExpiredIdTokenError(f"Token expired: {TOKEN}", None),
            auth.CertificateFetchError(f"Fallo con {TOKEN}", None),
        )
        for error in errors:
            with self.subTest(error=type(error).__name__):
                verify.side_effect = error
                with self.assertLogs("accounts.authentication", level="INFO") as logs:
                    with self.assertRaises((AuthenticationFailed, TokenVerificationUnavailable)) as raised:
                        uid_from_request(request_with(f"Bearer {TOKEN}"))
                self.assertNotIn(TOKEN, "\n".join(logs.output))
                self.assertNotIn(TOKEN, str(raised.exception))
                # Sin encadenar: un traceback no arrastra el mensaje original.
                self.assertIsNone(raised.exception.__cause__)
                self.assertTrue(raised.exception.__suppress_context__)

    def test_certificate_fetch_failure_is_not_a_401(self, verify, get_app):
        verify.side_effect = auth.CertificateFetchError("sin red", None)
        with self.assertLogs("accounts.authentication", level="ERROR"):
            with self.assertRaises(TokenVerificationUnavailable):
                uid_from_request(request_with(f"Bearer {TOKEN}"))

    def test_configuration_errors_propagate(self, verify, get_app):
        get_app.side_effect = FirebaseConfigError("sin credenciales")
        with self.assertRaises(FirebaseConfigError):
            uid_from_request(request_with(f"Bearer {TOKEN}"))

        get_app.side_effect = None
        verify.side_effect = ValueError("Failed to ascertain project ID")
        with self.assertRaises(ValueError):
            uid_from_request(request_with(f"Bearer {TOKEN}"))
