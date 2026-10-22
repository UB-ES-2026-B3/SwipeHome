import json
import os
import tempfile
from unittest.mock import patch

from django.test import SimpleTestCase

from . import firebase
from .firebase import FirebaseConfigError

CREDENTIAL_VARS = (
    "FIREBASE_SERVICE_ACCOUNT_JSON",
    "GOOGLE_APPLICATION_CREDENTIALS",
    "FIREBASE_PROJECT_ID",
    "FIREBASE_STORAGE_BUCKET",
)
FAKE_SECRET = "-----BEGIN PRIVATE KEY-----secreto-----END PRIVATE KEY-----"


def env_without_credentials(**values):
    """Entorno sin ninguna credencial de Firebase salvo las indicadas."""
    env = {key: value for key, value in os.environ.items() if key not in CREDENTIAL_VARS}
    env.update(values)
    return patch.dict(os.environ, env, clear=True)


@patch("accounts.firebase.firebase_admin.initialize_app")
@patch("accounts.firebase.firebase_admin.get_app", side_effect=ValueError("sin app"))
class GetAppTests(SimpleTestCase):
    def test_without_credentials_fails_with_clear_message(self, get_app, initialize_app):
        with env_without_credentials(), self.assertRaises(FirebaseConfigError) as raised:
            with self.assertLogs("accounts.firebase", level="ERROR"):
                firebase.get_app()
        self.assertIn("FIREBASE_SERVICE_ACCOUNT_JSON", str(raised.exception))
        self.assertIn("GOOGLE_APPLICATION_CREDENTIALS", str(raised.exception))
        initialize_app.assert_not_called()

    def test_configuration_error_is_logged_with_its_cause_and_no_secret(self, get_app, initialize_app):
        # En producción el log es lo único que dice qué falla de la credencial.
        cases = {
            "ausente": ({}, "No hay credenciales"),
            "json roto": ({"FIREBASE_SERVICE_ACCOUNT_JSON": '{"private_key": "' + FAKE_SECRET}, "no contiene un JSON válido"),
            "no es cuenta de servicio": (
                {"FIREBASE_SERVICE_ACCOUNT_JSON": json.dumps({"type": "authorized_user", "private_key": FAKE_SECRET})},
                "no es una cuenta de servicio",
            ),
        }
        for case, (env, expected) in cases.items():
            with self.subTest(case=case), env_without_credentials(**env):
                with self.assertLogs("accounts.firebase", level="ERROR") as logs, self.assertRaises(FirebaseConfigError):
                    firebase.get_app()
                self.assertEqual(len(logs.output), 1)
                self.assertIn(expected, logs.output[0])
                self.assertNotIn(FAKE_SECRET, logs.output[0])

    def test_blank_variables_count_as_missing(self, get_app, initialize_app):
        with env_without_credentials(FIREBASE_SERVICE_ACCOUNT_JSON="  ", GOOGLE_APPLICATION_CREDENTIALS=""):
            with self.assertRaises(FirebaseConfigError):
                firebase.get_app()

    def test_invalid_json_does_not_leak_content(self, get_app, initialize_app):
        with env_without_credentials(FIREBASE_SERVICE_ACCOUNT_JSON='{"private_key": "' + FAKE_SECRET):
            with self.assertRaises(FirebaseConfigError) as raised:
                firebase.get_app()
        self.assertNotIn(FAKE_SECRET, str(raised.exception))
        self.assertIsNone(raised.exception.__cause__)
        self.assertTrue(raised.exception.__suppress_context__)

    def test_json_that_is_not_a_service_account_fails_clearly(self, get_app, initialize_app):
        # Certificate real, sin mock: rechaza el dict sin tocar la red.
        payload = json.dumps({"type": "authorized_user", "private_key": FAKE_SECRET})
        with env_without_credentials(FIREBASE_SERVICE_ACCOUNT_JSON=payload):
            with self.assertRaises(FirebaseConfigError) as raised:
                firebase.get_app()
        self.assertNotIn(FAKE_SECRET, str(raised.exception))
        initialize_app.assert_not_called()

    @patch("accounts.firebase.credentials.Certificate")
    def test_json_variable_initializes_with_its_content(self, certificate, get_app, initialize_app):
        info = {"type": "service_account", "project_id": "swipehome-a51d7"}
        with env_without_credentials(FIREBASE_SERVICE_ACCOUNT_JSON=json.dumps(info), FIREBASE_PROJECT_ID="swipehome-a51d7"):
            app = firebase.get_app()
        certificate.assert_called_once_with(info)
        initialize_app.assert_called_once_with(certificate.return_value, {"projectId": "swipehome-a51d7"})
        self.assertIs(app, initialize_app.return_value)

    @patch("accounts.firebase.credentials.Certificate")
    def test_json_variable_takes_precedence_over_file(self, certificate, get_app, initialize_app):
        info = {"type": "service_account"}
        with env_without_credentials(
            FIREBASE_SERVICE_ACCOUNT_JSON=json.dumps(info),
            GOOGLE_APPLICATION_CREDENTIALS="C:/no/existe.json",
        ):
            firebase.get_app()
        certificate.assert_called_once_with(info)

    @patch("accounts.firebase.credentials.Certificate")
    def test_file_variable_initializes_from_path(self, certificate, get_app, initialize_app):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "cuenta.json")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("{}")
            with env_without_credentials(GOOGLE_APPLICATION_CREDENTIALS=path):
                firebase.get_app()
        certificate.assert_called_once_with(path)
        # Sin FIREBASE_PROJECT_ID, el project id sale de la propia credencial.
        initialize_app.assert_called_once_with(certificate.return_value, None)

    def test_missing_file_fails_naming_the_path(self, get_app, initialize_app):
        missing = os.path.join(tempfile.gettempdir(), "swipehome-no-existe.json")
        with env_without_credentials(GOOGLE_APPLICATION_CREDENTIALS=missing):
            with self.assertRaises(FirebaseConfigError) as raised:
                firebase.get_app()
        self.assertIn(missing, str(raised.exception))
        initialize_app.assert_not_called()


class GetAppAlreadyInitializedTests(SimpleTestCase):
    @patch("accounts.firebase.firebase_admin.initialize_app")
    @patch("accounts.firebase.firebase_admin.get_app")
    def test_reuses_existing_app_without_reading_credentials(self, get_app, initialize_app):
        with env_without_credentials():
            app = firebase.get_app()
        self.assertIs(app, get_app.return_value)
        initialize_app.assert_not_called()
