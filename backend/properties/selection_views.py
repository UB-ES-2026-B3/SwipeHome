"""API de propuestas con identidad de Firebase."""
import json
import logging
import re

from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from accounts import repository
from accounts.authentication import firebase_roles
from accounts.pagination import InvalidQuery, valid_document_id
from .selection_service import list_selections, selection_detail, selection_item

logger = logging.getLogger(__name__)
KEY = re.compile(r"[A-Za-z0-9_-]{16,128}")
SELECTION_ID = re.compile(r"[0-9a-f]{64}")


def _json_object(request, fields):
    if request.content_type != "application/json":
        raise ValueError()
    body = json.loads(request.body)
    if not isinstance(body, dict) or set(body) != fields:
        raise ValueError()
    if any(not isinstance(value, str) for value in body.values()):
        raise ValueError()
    return body


def _not_found():
    return JsonResponse({"error": "Propuesta o candidatura no encontrada."}, status=404)


def _conflict():
    return JsonResponse({"error": "El anuncio o la propuesta ya tiene un estado incompatible."}, status=409)


def _unavailable(error):
    logger.error("Falló la operación de propuestas (%s).", type(error).__name__)
    return JsonResponse({"error": "No se pudo completar la operación. Inténtalo de nuevo."}, status=500)


@never_cache
@require_POST
@firebase_roles("SELLER")
def create_selection(request, listing_id):
    try:
        body = _json_object(request, {"buyer_uid", "idempotency_key"})
        if not valid_document_id(body["buyer_uid"]) or not KEY.fullmatch(body["idempotency_key"]):
            raise ValueError()
        if not valid_document_id(listing_id):
            return _not_found()
    except (ValueError, RecursionError):
        return JsonResponse({"error": "Se requiere buyer_uid e idempotency_key válidos."}, status=400)
    try:
        selection, created = repository.create_selection(
            request.user.uid, request.user.name, listing_id, body["buyer_uid"], body["idempotency_key"],
        )
        return JsonResponse(selection_item(selection), status=201 if created else 200)
    except repository.SelectionNotFound:
        return _not_found()
    except repository.SelectionConflict:
        return _conflict()
    except Exception as error:
        return _unavailable(error)


@never_cache
@require_GET
@firebase_roles("BUYER", "SELLER")
def selections(request):
    try:
        return JsonResponse(list_selections(request.user, request.GET))
    except InvalidQuery:
        return JsonResponse({"error": "Los parámetros de consulta no son válidos."}, status=400)
    except Exception as error:
        return _unavailable(error)


@never_cache
@require_GET
@firebase_roles("BUYER", "SELLER")
def selection(request, selection_id):
    if not SELECTION_ID.fullmatch(selection_id):
        return _not_found()
    try:
        return JsonResponse(selection_detail(request.user, selection_id))
    except repository.SelectionNotFound:
        return _not_found()
    except Exception as error:
        return _unavailable(error)


@never_cache
@require_POST
@firebase_roles("BUYER", "SELLER")
def selection_decision(request, selection_id):
    try:
        action = _json_object(request, {"decision"})["decision"]
        if action not in repository.SELECTION_RESPONSES:
            raise ValueError()
    except (ValueError, RecursionError):
        return JsonResponse({"error": "Se requiere decision con valor ACCEPT, REJECT o CANCEL."}, status=400)
    if request.user.role != ("SELLER" if action == "CANCEL" else "BUYER"):
        return JsonResponse({"error": "La cuenta no tiene acceso a esta operación."}, status=403)
    if not SELECTION_ID.fullmatch(selection_id):
        return _not_found()
    try:
        record, changed = repository.transition_selection(request.user.uid, request.user.role, selection_id, action)
        return JsonResponse(selection_item(record), status=201 if changed else 200)
    except (repository.SelectionNotFound, repository.SelectionForbidden):
        return _not_found()
    except repository.SelectionConflict:
        return _conflict()
    except Exception as error:
        return _unavailable(error)
