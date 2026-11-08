"""Cliente único de Azure Blob Storage para las fotografías de los anuncios.

Configuración por variables de entorno:
- AZURE_STORAGE_CONNECTION_STRING (obligatoria): cadena de conexión de la
  cuenta de almacenamiento, con AccountName y AccountKey.
- AZURE_STORAGE_CONTAINER (opcional, "listings" por defecto): contenedor con
  nivel de acceso anónimo «Blob», para que las URLs se lean sin credenciales.

La cadena de conexión contiene la clave de la cuenta: nunca se escribe en los
logs ni en los mensajes de las excepciones. Igual que `firebase.py`, el cliente
se crea de forma perezosa la primera vez que se necesita, así que
`manage.py check`, /api/health y los tests mockeados funcionan sin ella.
"""
import binascii
import logging
import os
import threading
from base64 import b64decode

from azure.storage.blob import BlobServiceClient

logger = logging.getLogger(__name__)
_init_lock = threading.Lock()
_container = None

DEFAULT_CONTAINER = "listings"


class StorageConfigError(RuntimeError):
    """Falta la configuración de Azure Blob Storage o no es válida."""


def get_container_client():
    """Devuelve el cliente del contenedor de fotografías, creándolo una sola vez.

    Los clientes del SDK de Azure son seguros entre hilos: se comparte uno.
    """
    global _container
    if _container is not None:
        return _container
    # Dos peticiones simultáneas podrían intentar crearlo a la vez.
    with _init_lock:
        if _container is None:
            try:
                _container = _create_container_client()
            except StorageConfigError as error:
                # Los mensajes de StorageConfigError nunca incluyen la cadena:
                # se registran enteros para saber en Render qué falla.
                logger.error("%s", error)
                raise
        return _container


def _create_container_client():
    connection_string = os.environ.get("AZURE_STORAGE_CONNECTION_STRING", "").strip()
    if not connection_string:
        raise StorageConfigError(
            "Falta AZURE_STORAGE_CONNECTION_STRING: define la cadena de conexión "
            "de la cuenta de Azure Storage (Portal → Claves de acceso)."
        )
    _check_connection_string(connection_string)
    container = os.environ.get("AZURE_STORAGE_CONTAINER", "").strip() or DEFAULT_CONTAINER
    # `from None`: la excepción original podría llevar la cadena de conexión.
    try:
        service = BlobServiceClient.from_connection_string(connection_string)
    except ValueError:
        raise StorageConfigError(
            "AZURE_STORAGE_CONNECTION_STRING no es una cadena de conexión válida."
        ) from None
    return service.get_container_client(container)


def _check_connection_string(connection_string):
    """Rechaza cadenas que el SDK aceptaría y solo fallarían al subir."""
    fields = {}
    for part in connection_string.split(";"):
        key, separator, value = part.partition("=")
        if separator:
            fields[key.strip().lower()] = value.strip()
    if not fields.get("accountname"):
        raise StorageConfigError(
            "AZURE_STORAGE_CONNECTION_STRING no es válida: falta AccountName."
        )
    if "sharedaccesssignature" in fields:
        # El token SAS acabaría dentro de las URLs públicas guardadas en Firestore.
        raise StorageConfigError(
            "AZURE_STORAGE_CONNECTION_STRING no es válida: usa la cadena con "
            "AccountKey, no una con SharedAccessSignature."
        )
    try:
        valid_key = bool(b64decode(fields.get("accountkey", ""), validate=True))
    except (binascii.Error, ValueError):
        valid_key = False
    if not valid_key:
        raise StorageConfigError(
            "AZURE_STORAGE_CONNECTION_STRING no es válida: falta AccountKey "
            "o no está en base64."
        )
