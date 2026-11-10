"""Operaciones sobre la cuenta identificada exclusivamente por el token verificado."""
import json
import logging

from django.http import HttpResponse, JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods, require_POST
from firebase_admin import auth
from firebase_admin.exceptions import InvalidArgumentError

from . import repository
from .authentication import AuthenticationFailed, verified_session
from .firebase import get_app
from .passwords import IncorrectPassword, PasswordRejected, change_password
from .profile_validation import validate_password_change, validate_profile_update

logger = logging.getLogger(__name__)


def failure():
    return JsonResponse({"error": "No se pudo completar la operación. Inténtalo de nuevo."}, status=500)


def unauthorized():
    response = JsonResponse({"error": "No hay una sesión autenticada."}, status=401)
    response["WWW-Authenticate"] = "Bearer"
    return response


def json_body(request):
    if request.content_type != "application/json":
        raise ValueError()
    return json.loads(request.body)


@never_cache
@require_http_methods(["PATCH", "PUT"])
def update_profile(request):
    try:
        session = verified_session(request)
        try:
            values, errors = validate_profile_update(json_body(request))
        except (ValueError, UnicodeDecodeError):
            return JsonResponse({"error": "Se requiere un objeto application/json válido."}, status=400)
        if errors:
            return JsonResponse({"errors": errors}, status=400)
        # Firmar antes de escribir evita cambios si falla la credencial de firma.
        continuity = None
        if "email" in values:
            continuity = auth.create_custom_token(session["uid"], app=get_app()).decode("ascii")
        profile = repository.update_user_profile(session["uid"], values)
        if profile is None:
            return JsonResponse({"error": "Tu cuenta está incompleta."}, status=404)
        if continuity:
            profile["custom_token"] = continuity
        return JsonResponse(profile)
    except AuthenticationFailed:
        return unauthorized()
    except auth.EmailAlreadyExistsError:
        return JsonResponse({"error": "El email ya está registrado."}, status=409)
    except InvalidArgumentError:
        return JsonResponse({"error": "Los datos no son válidos."}, status=400)
    except Exception as error:
        logger.error("Falló la actualización de perfil (%s).", type(error).__name__)
        return failure()


@never_cache
@sensitive_post_parameters("current_password", "new_password")
@require_POST
def password(request):
    try:
        session = verified_session(request)
        try:
            data = json_body(request)
        except (ValueError, UnicodeDecodeError):
            return JsonResponse({"error": "Se requiere un objeto application/json válido."}, status=400)
        errors = validate_password_change(data)
        if errors:
            return JsonResponse({"errors": errors}, status=400)
        if repository.get_user_profile(session["uid"]) is None:
            return JsonResponse({"error": "Tu cuenta está incompleta."}, status=404)
        token = change_password(session["uid"], data["current_password"], data["new_password"])
        # Credencial de continuidad intencionada, solo en esta respuesta no-store.
        # El SDK debe intercambiarla inmediatamente; nunca se persiste en la aplicación.
        return JsonResponse({"custom_token": token})
    except AuthenticationFailed:
        return unauthorized()
    except IncorrectPassword:
        return JsonResponse({"errors": {"current_password": "La contraseña actual no es correcta."}}, status=400)
    except (PasswordRejected, InvalidArgumentError):
        return JsonResponse({"errors": {"new_password": "Firebase ha rechazado la nueva contraseña."}}, status=400)
    except Exception as error:
        logger.error("Falló el cambio de contraseña (%s).", type(error).__name__)
        return failure()


@never_cache
@require_POST
def logout(request):
    try:
        # Permite repetir la revocación; sigue verificando firma, caducidad y cuenta.
        session = verified_session(request, allow_revoked=True)
        repository.revoke_session(session["uid"], session["auth_time"])
        return HttpResponse(status=204)
    except AuthenticationFailed:
        # Ausente, caducada o revocada por Firebase: ya no permite acceder.
        return HttpResponse(status=204)
    except Exception as error:
        logger.error("Falló el cierre de sesión (%s).", type(error).__name__)
        return failure()
