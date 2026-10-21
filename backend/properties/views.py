import json
import logging

from django.http import JsonResponse
from django.views.decorators.http import require_POST

from accounts import repository
from accounts.authentication import AuthenticationFailed, TokenVerificationUnavailable, uid_from_request
from .validation import validate_photo_urls, validate_property

logger = logging.getLogger(__name__)


@require_POST
def create_property(request):
    if request.content_type != "application/json":
        return JsonResponse({"error": "Se requiere application/json."}, status=400)
    try:
        data = json.loads(request.body)
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({"error": "JSON inválido."}, status=400)
    if not isinstance(data, dict):
        return JsonResponse({"error": "El cuerpo debe ser un objeto JSON."}, status=400)

    try:
        uid = uid_from_request(request)
    except AuthenticationFailed:
        return JsonResponse({"error": "Se requiere una sesión autenticada."}, status=401)
    except TokenVerificationUnavailable:
        logger.error("No se pudo verificar el token al publicar un inmueble.")
        return JsonResponse({"error": "No se pudo verificar la sesión. Inténtalo de nuevo."}, status=500)
    except Exception as error:
        logger.error("Error inesperado verificando la sesión (%s).", type(error).__name__)
        return JsonResponse({"error": "No se pudo verificar la sesión. Inténtalo de nuevo."}, status=500)

    try:
        profile = repository.get_user_profile(uid)
    except Exception as error:
        logger.error("No se pudo leer el perfil del vendedor %s (%s).", uid, type(error).__name__)
        return JsonResponse({"error": "No se pudo comprobar el usuario. Inténtalo de nuevo."}, status=500)
    if profile is None:
        return JsonResponse({"error": "La cuenta no tiene un perfil completo."}, status=403)
    if profile["role"] != "SELLER":
        return JsonResponse({"error": "Solo los vendedores pueden publicar inmuebles."}, status=403)

    values, errors = validate_property(data)
    photos, photo_errors = validate_photo_urls(data)
    errors.update(photo_errors)
    if errors:
        return JsonResponse({"errors": errors}, status=400)

    try:
        listing = repository.create_listing(uid, values=values, photo_urls=photos)
    except Exception as error:
        logger.error("No se pudo guardar la publicación del vendedor %s (%s).", uid, type(error).__name__)
        return JsonResponse(
            {"error": "No se pudo completar la publicación. Inténtalo de nuevo."},
            status=500,
        )
    return JsonResponse(listing, status=201)
