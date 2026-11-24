from unittest.mock import patch

from django.test import SimpleTestCase

from qa.environment import LOCAL_ENV, blob_container, require_firebase


class LocalEnvironmentTests(SimpleTestCase):
    def test_local_project_and_emulators_are_required(self):
        with patch.dict("os.environ", LOCAL_ENV, clear=True):
            require_firebase()
        for key, value in (
            ("FIRESTORE_EMULATOR_HOST", "firestore.googleapis.com:443"),
            ("FIREBASE_AUTH_EMULATOR_HOST", ""),
            ("GOOGLE_CLOUD_PROJECT", "production"),
            ("FIREBASE_SERVICE_ACCOUNT_JSON", "unexpected"),
        ):
            with self.subTest(key=key), patch.dict("os.environ", {**LOCAL_ENV, key: value}, clear=True):
                with self.assertRaises(RuntimeError):
                    require_firebase()

    @patch("accounts.azure_storage.get_container_client")
    def test_azurite_rejects_a_remote_connection_or_cached_client(self, client):
        with patch.dict("os.environ", {**LOCAL_ENV, "AZURE_STORAGE_CONNECTION_STRING": "remote"}, clear=True):
            with self.assertRaises(RuntimeError):
                blob_container()
        client.assert_not_called()

        client.return_value.url = "https://remote.invalid/listings"
        with patch.dict("os.environ", LOCAL_ENV, clear=True):
            with self.assertRaises(RuntimeError):
                blob_container()
