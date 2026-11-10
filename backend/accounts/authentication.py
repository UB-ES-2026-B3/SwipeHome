"""Verificación Firebase y revocación persistente de la sesión de SwipeHome."""
import logging

from firebase_admin import auth

from . import repository
from .firebase import get_app

logger = logging.getLogger(__name__)
MISSING = "missing"
MALFORMED = "malformed"
INVALID = "invalid"
EXPIRED = "expired"


class AuthenticationFailed(Exception):
    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


class TokenVerificationUnavailable(Exception):
    """Fallo del servidor: nunca debe convertirse en cierre de sesión (401)."""


def verified_session(request, *, allow_revoked=False):
    header = request.headers.get("Authorization", "").strip()
    if not header:
        logger.info("Petición sin cabecera Authorization.")
        raise AuthenticationFailed(MISSING)
    scheme, _, token = header.partition(" ")
    token = token.strip()
    if scheme.lower() != "bearer" or not token or any(c.isspace() for c in token):
        logger.warning("Cabecera Authorization mal formada.")
        raise AuthenticationFailed(MALFORMED)
    try:
        decoded = auth.verify_id_token(
            token,
            app=get_app(),
            check_revoked=True,
            clock_skew_seconds=10,
        )
    except auth.ExpiredIdTokenError:
        logger.info("ID token caducado.")
        raise AuthenticationFailed(EXPIRED) from None
    except (auth.InvalidIdTokenError, auth.UserDisabledError, auth.UserNotFoundError):
        logger.warning("ID token inválido o cuenta deshabilitada.")
        raise AuthenticationFailed(INVALID) from None
    except auth.CertificateFetchError:
        logger.error("No se pudieron descargar los certificados de Google.")
        raise TokenVerificationUnavailable() from None
    if (
        not isinstance(decoded.get("uid"), str) or not decoded["uid"]
        or type(decoded.get("auth_time")) is not int or decoded["auth_time"] < 0
    ):
        raise AuthenticationFailed(INVALID)
    if not allow_revoked and repository.is_session_revoked(decoded["uid"], decoded["auth_time"]):
        raise AuthenticationFailed(INVALID)
    return decoded


def uid_from_request(request):
    return verified_session(request)["uid"]


def firebase_role(role):
    """Construye request.user solo desde Auth verificado y perfil del servidor."""
    from functools import wraps
    from types import SimpleNamespace

    from django.http import JsonResponse

    def decorate(view):
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            try:
                session = verified_session(request)
                profile = repository.get_user_profile(session["uid"])
                if profile is None or profile["role"] != role:
                    return JsonResponse({"error": "La cuenta no tiene acceso a esta operación."}, status=403)
                request.user = SimpleNamespace(
                    uid=session["uid"], role=profile["role"], name=profile.get("name", ""),
                    is_authenticated=True,
                )
            except AuthenticationFailed:
                response = JsonResponse({"error": "No hay una sesión autenticada."}, status=401)
                response["WWW-Authenticate"] = "Bearer"
                return response
            except Exception as error:
                logger.error("No se pudo comprobar el acceso (%s).", type(error).__name__)
                return JsonResponse({"error": "No se pudo verificar la sesión. Inténtalo de nuevo."}, status=500)
            return view(request, *args, **kwargs)
        return wrapped
    return decorate
