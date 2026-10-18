import json
import logging

from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_GET, require_POST
from firebase_admin import auth

from . import repository
from .authentication import AuthenticationFailed, uid_from_request
from .firebase import get_app
from .validation import validate_registration

logger = logging.getLogger(__name__)

# Nunca se registra el payload, el token ni el mensaje de las excepciones:
# pueden contener la contraseña o el propio token. Solo el tipo de error y el uid.


def registration_error():
    return JsonResponse({"error": "No se pudo completar el registro. Inténtalo de nuevo."}, status=500)


def current_user_error():
    return JsonResponse({"error": "No se pudo consultar el usuario. Inténtalo de nuevo."}, status=500)


def discard_firebase_user(uid):
    """Acción compensatoria: borra el usuario de Firebase Auth que se quedó sin perfil."""
    try:
        auth.delete_user(uid, app=get_app())
    except Exception as error:
        # El usuario queda huérfano: recuperación manual desde la consola (§3 de la spec).
        logger.error(
            "Falló el borrado compensatorio (%s): el usuario %s de Firebase Auth queda sin perfil.",
            type(error).__name__, uid,
        )


# Sin cookies de sesión no hay nada que proteger con CSRF. Puente hasta que se
# retire CsrfViewMiddleware de settings.py.
@csrf_exempt
@sensitive_post_parameters("password")
@require_POST
def register(request):
    if request.content_type != "application/json":
        return JsonResponse({"error": "Se requiere application/json."}, status=400)
    try:
        data = json.loads(request.body)
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({"error": "JSON inválido."}, status=400)
    values, errors = validate_registration(data)
    if errors:
        return JsonResponse({"errors": errors}, status=400)

    try:
        firebase_user = auth.create_user(email=values["email"], password=values["password"], app=get_app())
    except auth.EmailAlreadyExistsError:
        # Firebase Auth garantiza la unicidad del email; no hay nada que deshacer.
        return JsonResponse({"error": "El email ya está registrado."}, status=409)
    except Exception as error:
        logger.error("No se pudo crear el usuario en Firebase Auth (%s).", type(error).__name__)
        return registration_error()

    try:
        profile = repository.create_user_profile(
            firebase_user.uid, name=values["name"], email=values["email"], role=values["role"],
        )
    except Exception as error:
        # No hay transacciones entre Firebase Auth y Firestore: se deshace a mano.
        logger.error(
            "No se pudo guardar el perfil del usuario %s en Firestore (%s); se borra de Firebase Auth.",
            firebase_user.uid, type(error).__name__,
        )
        discard_firebase_user(firebase_user.uid)
        return registration_error()
    return JsonResponse(profile, status=201)


@never_cache
@require_GET
def current_user(request):
    """Identidad a partir del ID token verificado, nunca de campos enviados por el cliente."""
    try:
        uid = uid_from_request(request)
    except AuthenticationFailed:
        response = JsonResponse({"error": "No hay una sesión autenticada."}, status=401)
        response["WWW-Authenticate"] = "Bearer"
        return response
    except Exception as error:
        # Fallo del servidor (credencial, certificados de Google...): no es un 401.
        logger.error("No se pudo verificar el token (%s).", type(error).__name__)
        return current_user_error()

    try:
        profile = repository.get_user_profile(uid)
    except Exception as error:
        logger.error("No se pudo leer el perfil del usuario %s en Firestore (%s).", uid, type(error).__name__)
        return current_user_error()
    if profile is None:
        # Integridad de datos, no autenticación: falló también el borrado compensatorio.
        logger.error("Usuario huérfano: %s existe en Firebase Auth pero no tiene perfil en Firestore.", uid)
        return JsonResponse(
            {"error": "Tu cuenta está incompleta. Contacta con el equipo de SwipeHome."}, status=404,
        )
    return JsonResponse(profile)


def csrf_failure(request, reason=""):
    # Referenciada por CSRF_FAILURE_VIEW; se elimina junto con el CSRF de settings.py.
    return JsonResponse({"error": "Verificacion CSRF rechazada."}, status=403)
