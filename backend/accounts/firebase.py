"""Inicialización única del Admin SDK de Firebase.

La credencial se lee, por este orden, de:
1. FIREBASE_SERVICE_ACCOUNT_JSON: contenido JSON completo (Render).
2. GOOGLE_APPLICATION_CREDENTIALS: ruta a un fichero JSON fuera del repositorio (local).

La inicialización es perezosa: solo ocurre la primera vez que alguien necesita
Firebase. Así `manage.py check`, los tests mockeados y /api/health funcionan
sin credenciales.
"""
import json
import logging
import os
import threading

import firebase_admin
from firebase_admin import credentials

logger = logging.getLogger(__name__)
_init_lock = threading.Lock()


class FirebaseConfigError(RuntimeError):
    """Falta la credencial de Firebase o no es válida."""


def get_app():
    """Devuelve la app de Firebase por defecto, inicializándola una sola vez."""
    try:
        return firebase_admin.get_app()
    except ValueError:
        pass
    # Dos peticiones simultáneas podrían intentar inicializarla a la vez.
    with _init_lock:
        try:
            return firebase_admin.get_app()
        except ValueError:
            pass
        try:
            credential = _load_credential()
        except FirebaseConfigError as error:
            # Los mensajes de FirebaseConfigError no contienen secretos: se registran
            # enteros para saber en los logs de Render qué falla exactamente.
            logger.error("%s", error)
            raise
        return firebase_admin.initialize_app(credential, _app_options())


def _app_options():
    project_id = os.environ.get("FIREBASE_PROJECT_ID", "").strip()
    storage_bucket = os.environ.get("FIREBASE_STORAGE_BUCKET", "").strip()
    options = {}
    if project_id:
        options["projectId"] = project_id
    if storage_bucket:
        options["storageBucket"] = storage_bucket
    return options or None


def _load_credential():
    raw_json = os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON", "").strip()
    if raw_json:
        # `from None`: la excepción original puede llevar dentro la clave privada.
        try:
            info = json.loads(raw_json)
        except ValueError:
            raise FirebaseConfigError(
                "FIREBASE_SERVICE_ACCOUNT_JSON no contiene un JSON válido."
            ) from None
        try:
            return credentials.Certificate(info)
        except ValueError:
            raise FirebaseConfigError(
                "FIREBASE_SERVICE_ACCOUNT_JSON no es una cuenta de servicio de Firebase válida."
            ) from None

    path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    if path:
        if not os.path.isfile(path):
            raise FirebaseConfigError(
                f"GOOGLE_APPLICATION_CREDENTIALS apunta a un fichero que no existe: {path}"
            )
        try:
            return credentials.Certificate(path)
        except ValueError:
            raise FirebaseConfigError(
                f"El fichero de GOOGLE_APPLICATION_CREDENTIALS no es una cuenta de servicio válida: {path}"
            ) from None

    raise FirebaseConfigError(
        "No hay credenciales de Firebase. Define FIREBASE_SERVICE_ACCOUNT_JSON (contenido JSON, "
        "en Render) o GOOGLE_APPLICATION_CREDENTIALS (ruta al JSON de la cuenta de servicio, en local)."
    )
