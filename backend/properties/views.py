import logging
import json

from django.http import JsonResponse
from django.views.decorators.http import require_http_methods, require_GET, require_POST

from accounts import repository
from accounts.authentication import AuthenticationFailed, TokenVerificationUnavailable, uid_from_request
from .validation import photo_uploads, validate_photos, validate_property

logger = logging.getLogger(__name__)


def _authenticated_uid(request):
    try:
        return uid_from_request(request)
    except AuthenticationFailed:
        return None
    except TokenVerificationUnavailable:
        raise


@require_GET
def explore_properties(request):
    try:
        uid = _authenticated_uid(request)
        if uid is None:
            return JsonResponse({"error": "Se requiere una sesión autenticada."}, status=401)
        limit = int(request.GET.get("limit", "10"))
        offset = int(request.GET.get("offset", "0"))
        if not 1 <= limit <= 20 or offset < 0:
            raise ValueError
        items, next_offset = repository.get_explorable_listings(uid, limit=limit, offset=offset)
        return JsonResponse({"items": items, "next_offset": next_offset})
    except ValueError:
        return JsonResponse({"error": "Los parámetros de exploración no son válidos."}, status=400)
    except TokenVerificationUnavailable:
        logger.error("No se pudo verificar el token al explorar inmuebles.")
        return JsonResponse({"error": "No se pudo verificar la sesión. Inténtalo de nuevo."}, status=500)
    except Exception as error:
        logger.error("No se pudieron explorar los inmuebles (%s).", type(error).__name__)
        return JsonResponse({"error": "No se pudieron cargar las viviendas. Inténtalo de nuevo."}, status=500)


@require_POST
def decide_property(request):
    try:
        uid = _authenticated_uid(request)
        if uid is None:
            return JsonResponse({"error": "Se requiere una sesión autenticada."}, status=401)
        data = json.loads(request.body)
        property_id = data.get("property_id")
        decision = data.get("decision")
        if (
            not isinstance(property_id, str)
            or not property_id
            or set(data) != {"property_id", "decision"}
            or decision not in {"LIKE", "PASS"}
        ):
            return JsonResponse({"error": "La decisión no es válida."}, status=400)
        result = repository.save_property_decision(uid, property_id, decision)
        return JsonResponse(result)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Se requiere un objeto JSON válido."}, status=400)
    except ValueError:
        return JsonResponse({"error": "La vivienda ya tiene una decisión incompatible."}, status=409)
    except LookupError:
        return JsonResponse({"error": "La vivienda ya no está disponible."}, status=404)
    except PermissionError:
        return JsonResponse({"error": "No puedes decidir sobre esta vivienda."}, status=403)
    except TokenVerificationUnavailable:
        logger.error("No se pudo verificar el token al guardar una decisión.")
        return JsonResponse({"error": "No se pudo verificar la sesión. Inténtalo de nuevo."}, status=500)
    except Exception as error:
        logger.error("No se pudo guardar la decisión (%s).", type(error).__name__)
        return JsonResponse({"error": "No se pudo guardar la decisión. Inténtalo de nuevo."}, status=500)


@require_http_methods(["GET", "POST"])
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

    if request.method == "GET":
        try:
            return JsonResponse({"properties": repository.get_seller_listings(uid)})
        except Exception as error:
            logger.error("No se pudieron leer los inmuebles del vendedor (%s).", type(error).__name__)
            return JsonResponse({"error": "No se pudieron cargar las viviendas. Inténtalo de nuevo."}, status=500)

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
