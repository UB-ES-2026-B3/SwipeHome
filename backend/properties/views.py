import logging

from django.http import JsonResponse
from django.views.decorators.http import require_POST

from accounts import repository
from accounts.authentication import AuthenticationFailed, TokenVerificationUnavailable, uid_from_request
from .validation import photo_uploads, validate_photos, validate_property

logger = logging.getLogger(__name__)


@require_POST
def create_property(request):
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

    if not request.content_type.startswith("multipart/form-data"):
        return JsonResponse({"error": "Se requiere multipart/form-data."}, status=400)
    values, errors = validate_property(request.POST)
    photos = photo_uploads(request.FILES)
    errors.update(validate_photos(photos))
    if errors:
        return JsonResponse({"errors": errors}, status=400)

    try:
        listing = repository.create_listing(uid, values=values, photos=photos)
    except Exception as error:
        logger.error("No se pudo guardar la publicación del vendedor %s (%s).", uid, type(error).__name__)
        return JsonResponse(
            {"error": "No se pudo completar la publicación. Inténtalo de nuevo."},
            status=500,
        )
    return JsonResponse(listing, status=201)
