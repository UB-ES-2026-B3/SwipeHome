"""API US4 con Firebase Bearer; no autentica cookies."""
import json
import logging

from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from accounts.authentication import firebase_role
from accounts.pagination import InvalidQuery, valid_document_id
from accounts.repository import DecisionConflict, ListingNotFound
from .discovery_service import decide, explore

logger = logging.getLogger(__name__)


@never_cache
@require_GET
@firebase_role("BUYER")
def explore_listings(request):
    try:
        return JsonResponse(explore(request.user, request.GET))
    except InvalidQuery:
        return JsonResponse({"error": "Los parámetros de consulta no son válidos."}, status=400)
    except Exception as error:
        logger.error("Falló la exploración (%s).", type(error).__name__)
        return JsonResponse({"error": "No se pudieron consultar los inmuebles."}, status=500)


@never_cache
@require_POST
@firebase_role("BUYER")
def listing_decision(request, listing_id):
    if request.content_type != "application/json":
        return JsonResponse({"error": "Se requiere application/json."}, status=400)
    try:
        body = json.loads(request.body)
        if (
            not isinstance(body, dict) or set(body) != {"decision"}
            or not isinstance(body["decision"], str) or body["decision"] not in {"LIKE", "PASS"}
        ):
            raise ValueError()
    except (ValueError, UnicodeDecodeError, RecursionError):
        return JsonResponse({"error": "Se requiere decision con valor LIKE o PASS."}, status=400)
    if not valid_document_id(listing_id):
        return JsonResponse({"error": "Inmueble no encontrado."}, status=404)
    try:
        payload, status = decide(request.user, listing_id, body["decision"])
        return JsonResponse(payload, status=status)
    except ListingNotFound:
        return JsonResponse({"error": "Inmueble no encontrado."}, status=404)
    except DecisionConflict:
        return JsonResponse({"error": "Ya existe una decisión diferente para este inmueble."}, status=409)
    except Exception as error:
        logger.error("Falló el guardado de la decisión (%s).", type(error).__name__)
        return JsonResponse({"error": "No se pudo guardar la decisión. Inténtalo de nuevo."}, status=500)
