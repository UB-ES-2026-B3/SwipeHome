"""Vistas de API para consulta de matches, candidatos y decisiones de vendedor (US5)."""
import json
import logging

from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from accounts.authentication import firebase_role
from accounts.pagination import InvalidQuery, valid_document_id
from accounts.repository import DecisionConflict, MatchNotFound
from .match_service import (
    ForbiddenProperty,
    decide_candidate,
    list_candidates,
    list_matches,
)

logger = logging.getLogger(__name__)


@never_cache
@require_GET
@firebase_role("BUYER", "SELLER")
def matches_view(request):
    try:
        return JsonResponse(list_matches(request.user, request.GET))
    except InvalidQuery:
        return JsonResponse({"error": "Los parámetros de consulta no son válidos."}, status=400)
    except ForbiddenProperty:
        return JsonResponse({"error": "La vivienda no está relacionada con el usuario."}, status=403)
    except Exception as error:
        logger.error("Falló la consulta de matches (%s).", type(error).__name__)
        return JsonResponse({"error": "No se pudieron consultar los matches."}, status=500)


@never_cache
@require_GET
@firebase_role("SELLER")
def candidates_view(request):
    try:
        return JsonResponse(list_candidates(request.user, request.GET))
    except InvalidQuery:
        return JsonResponse({"error": "Los parámetros de consulta no son válidos."}, status=400)
    except ForbiddenProperty:
        return JsonResponse({"error": "La vivienda no está relacionada con el usuario."}, status=403)
    except Exception as error:
        logger.error("Falló la consulta de candidatos (%s).", type(error).__name__)
        return JsonResponse({"error": "No se pudieron consultar los candidatos."}, status=500)


@never_cache
@require_POST
@firebase_role("SELLER")
def seller_match_decision(request, match_id):
    if request.content_type != "application/json":
        return JsonResponse({"error": "Se requiere application/json."}, status=400)
    try:
        body = json.loads(request.body)
        if (
            not isinstance(body, dict)
            or set(body) != {"decision"}
            or not isinstance(body["decision"], str)
            or body["decision"] not in {"LIKE", "PASS"}
        ):
            raise ValueError()
    except (ValueError, UnicodeDecodeError, RecursionError):
        return JsonResponse({"error": "Se requiere decision con valor LIKE o PASS."}, status=400)
    if not valid_document_id(match_id):
        return JsonResponse({"error": "Candidatura no encontrada."}, status=404)
    try:
        payload, status = decide_candidate(request.user, match_id, body["decision"])
        return JsonResponse(payload, status=status)
    except MatchNotFound:
        return JsonResponse({"error": "Candidatura no encontrada."}, status=404)
    except DecisionConflict:
        return JsonResponse({"error": "Ya existe una decisión diferente para esta candidatura."}, status=409)
    except Exception as error:
        logger.error("Falló el guardado de la decisión del vendedor (%s).", type(error).__name__)
        return JsonResponse({"error": "No se pudo guardar la decisión. Inténtalo de nuevo."}, status=500)
