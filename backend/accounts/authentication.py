"""Extrae y verifica el ID token de Firebase de la cabecera Authorization.

El token nunca se escribe en los logs. Tampoco el mensaje de las excepciones
de firebase_admin: algunos incluyen el propio token.
"""
import logging

from firebase_admin import auth

from .firebase import get_app

logger = logging.getLogger(__name__)

MISSING = "missing"
MALFORMED = "malformed"
INVALID = "invalid"
EXPIRED = "expired"


class AuthenticationFailed(Exception):
    """El cliente no está autenticado: token ausente, mal formado, inválido o caducado (401)."""

    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


class TokenVerificationUnavailable(Exception):
    """No se pudo verificar el token por un fallo del servidor, no del cliente.

    No debe tratarse como 401: el frontend lo interpretaría como un cierre de sesión.
    """


def uid_from_request(request) -> str:
    """Devuelve el uid de Firebase del token `Authorization: Bearer <token>`.

    Lanza AuthenticationFailed o TokenVerificationUnavailable. Los errores de
    configuración (FirebaseConfigError, project id ausente) se propagan tal cual.
    """
    header = request.headers.get("Authorization", "").strip()
    if not header:
        logger.info("Petición sin cabecera Authorization.")
        raise AuthenticationFailed(MISSING)

    scheme, _, token = header.partition(" ")
    token = token.strip()
    if scheme.lower() != "bearer" or not token or any(char.isspace() for char in token):
        logger.warning("Cabecera Authorization mal formada: se esperaba 'Bearer <token>'.")
        raise AuthenticationFailed(MALFORMED)

    try:
        decoded = auth.verify_id_token(token, app=get_app())
    # ExpiredIdTokenError hereda de InvalidIdTokenError: debe ir antes.
    except auth.ExpiredIdTokenError:
        logger.info("ID token de Firebase caducado.")
        raise AuthenticationFailed(EXPIRED) from None
    except auth.InvalidIdTokenError as error:
        logger.warning("ID token de Firebase inválido (%s).", type(error).__name__)
        raise AuthenticationFailed(INVALID) from None
    except auth.CertificateFetchError:
        logger.error("No se pudieron descargar los certificados de Google para verificar el token.")
        raise TokenVerificationUnavailable() from None
    return decoded["uid"]
