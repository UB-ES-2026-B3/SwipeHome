"""Endpoints de lectura de matches y decisión de candidaturas."""
import json
import logging

from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from accounts.authentication import firebase_roles
from accounts.pagination import InvalidQuery, valid_document_id
from accounts.repository import DecisionConflict, ListingNotFound
from .match_service import decide_candidate, list_candidates, list_matches

logger = logging.getLogger(__name__)


@never_cache
@require_GET
@firebase_roles("BUYER", "SELLER")
def matches(request):
    try:
        return JsonResponse(list_matches(request.user, request.GET))
    except InvalidQuery:
        return JsonResponse({"error": "Los parámetros de consulta no son válidos."}, status=400)
    except Exception as error:
        logger.error("Falló la consulta de matches (%s).", type(error).__name__)
        return JsonResponse({"error": "No se pudieron consultar los matches."}, status=500)


@never_cache
@require_GET
@firebase_roles("SELLER")
def pending_candidates(request):
    try:
        return JsonResponse(list_candidates(request.user, request.GET))
    except InvalidQuery:
        return JsonResponse({"error": "Los parámetros de consulta no son válidos."}, status=400)
    except Exception as error:
        logger.error("Falló la consulta de candidaturas (%s).", type(error).__name__)
        return JsonResponse({"error": "No se pudieron consultar las candidaturas."}, status=500)


@never_cache
@require_POST
@firebase_roles("SELLER")
def candidate_decision(request, decision_id):
    if request.content_type != "application/json":
        return JsonResponse({"error": "Se requiere application/json."}, status=400)
    try:
        body = json.loads(request.body)
        if (
            not isinstance(body, dict) or set(body) != {"decision"}
            or not isinstance(body["decision"], str)
            or body["decision"] not in {"ACCEPT", "REJECT"}
        ):
            raise ValueError()
    except (ValueError, UnicodeDecodeError, RecursionError):
        return JsonResponse({"error": "Se requiere decision con valor ACCEPT o REJECT."}, status=400)
    if not valid_document_id(decision_id):
        return JsonResponse({"error": "Candidatura no encontrada."}, status=404)
    try:
        payload, status = decide_candidate(request.user, decision_id, body["decision"])
        return JsonResponse(payload, status=status)
    except ListingNotFound:
        return JsonResponse({"error": "Candidatura no encontrada."}, status=404)
    except DecisionConflict:
        return JsonResponse({"error": "La candidatura ya tiene una decisión diferente."}, status=409)
    except Exception as error:
        logger.error("Falló la decisión de candidatura (%s).", type(error).__name__)
        return JsonResponse({"error": "No se pudo guardar la decisión. Inténtalo de nuevo."}, status=500)
