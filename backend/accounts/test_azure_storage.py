import os
from unittest.mock import patch

from django.test import SimpleTestCase

from . import azure_storage
from .azure_storage import StorageConfigError

# Clave falsa en base64 válida; nunca debe aparecer en mensajes ni logs.
FAKE_KEY = "Q2xhdmVGYWxzYVNlY3JldGFEZVBydWViYQ=="
VALID = (
    "DefaultEndpointsProtocol=https;AccountName=swipehometest;"
    f"AccountKey={FAKE_KEY};EndpointSuffix=core.windows.net"
)


def storage_env(**values):
    """Entorno sin ninguna variable de Azure Storage salvo las indicadas."""
    env = {key: value for key, value in os.environ.items() if not key.startswith("AZURE_STORAGE_")}
    env.update(values)
    return patch.dict(os.environ, env, clear=True)


class GetContainerClientTests(SimpleTestCase):
    def setUp(self):
        # Cada test empieza sin cliente en caché.
        self.enterContext(patch.object(azure_storage, "_container", None))

    def test_missing_connection_string_fails_with_clear_message(self):
        for value in (None, "", "   "):
            env = {} if value is None else {"AZURE_STORAGE_CONNECTION_STRING": value}
            with self.subTest(value=value), storage_env(**env):
                with self.assertLogs("accounts.azure_storage", level="ERROR") as logs:
                    with self.assertRaises(StorageConfigError) as raised:
                        azure_storage.get_container_client()
                self.assertIn("AZURE_STORAGE_CONNECTION_STRING", str(raised.exception))
                self.assertEqual(len(logs.output), 1)

    def test_invalid_connection_strings_fail_without_leaking_the_secret(self):
        cases = {
            "basura": FAKE_KEY,
            "sin AccountName": f"DefaultEndpointsProtocol=https;AccountKey={FAKE_KEY}",
            "sin AccountKey": "DefaultEndpointsProtocol=https;AccountName=swipehometest",
            "clave no base64": f"AccountName=swipehometest;AccountKey=!{FAKE_KEY}!",
            "SAS": f"BlobEndpoint=https://x.blob.core.windows.net;AccountName=x;SharedAccessSignature=sig{FAKE_KEY}",
        }
        for case, value in cases.items():
            with self.subTest(case=case), storage_env(AZURE_STORAGE_CONNECTION_STRING=value):
                with self.assertLogs("accounts.azure_storage", level="ERROR") as logs:
                    with self.assertRaises(StorageConfigError) as raised:
                        azure_storage.get_container_client()
                message = str(raised.exception)
                self.assertIn("AZURE_STORAGE_CONNECTION_STRING", message)
                self.assertNotIn(FAKE_KEY, message)
                self.assertNotIn(FAKE_KEY, "\n".join(logs.output))
                # Ni la causa ni el contexto encadenados pueden llevar la cadena.
                self.assertIsNone(raised.exception.__cause__)
                self.assertTrue(
                    raised.exception.__context__ is None or raised.exception.__suppress_context__
                )

    def test_sdk_rejection_is_wrapped_without_original_exception(self):
        with storage_env(AZURE_STORAGE_CONNECTION_STRING=VALID), patch(
            "accounts.azure_storage.BlobServiceClient.from_connection_string",
            side_effect=ValueError("Connection string " + VALID),
        ):
            with self.assertLogs("accounts.azure_storage", level="ERROR") as logs:
                with self.assertRaises(StorageConfigError) as raised:
                    azure_storage.get_container_client()
        self.assertNotIn(FAKE_KEY, str(raised.exception))
        self.assertNotIn(FAKE_KEY, "\n".join(logs.output))
        self.assertIsNone(raised.exception.__cause__)
        self.assertTrue(raised.exception.__suppress_context__)

    def test_valid_connection_string_uses_default_container(self):
        # Cliente real del SDK: construirlo no hace ninguna petición de red.
        with storage_env(AZURE_STORAGE_CONNECTION_STRING=VALID):
            container = azure_storage.get_container_client()
        self.assertEqual(container.container_name, "listings")
        self.assertEqual(container.account_name, "swipehometest")
        blob = container.get_blob_client("listings/uid/abc")
        self.assertEqual(blob.url, "https://swipehometest.blob.core.windows.net/listings/listings/uid/abc")

    def test_container_can_be_overridden(self):
        with storage_env(AZURE_STORAGE_CONNECTION_STRING=VALID, AZURE_STORAGE_CONTAINER=" fotos "):
            self.assertEqual(azure_storage.get_container_client().container_name, "fotos")

    def test_client_is_created_once_and_reused(self):
        with storage_env(AZURE_STORAGE_CONNECTION_STRING=VALID):
            first = azure_storage.get_container_client()
        with storage_env():
            # Ya creado: no vuelve a leer la configuración.
            self.assertIs(azure_storage.get_container_client(), first)

    def test_configuration_error_is_not_cached(self):
        with storage_env(), self.assertLogs("accounts.azure_storage", level="ERROR"):
            with self.assertRaises(StorageConfigError):
                azure_storage.get_container_client()
        with storage_env(AZURE_STORAGE_CONNECTION_STRING=VALID):
            self.assertIsNotNone(azure_storage.get_container_client())
