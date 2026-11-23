"""US9: selección definitiva. Identidad y roles desde Firebase verificado."""
import json
import logging
from functools import wraps

from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from accounts import repository
from accounts.authentication import firebase_role
from accounts.pagination import InvalidQuery, page_result, parse_query, timestamp, valid_document_id
from .serialization import listing_item
from .validation import validate_property, FIELD_ALIASES

logger = logging.getLogger(__name__)
SALT = "properties.proposals.v1"


def payload(data):
    return {k: timestamp(v) if k in {"created_at", "resolved_at"} and v else v
            for k, v in data.items() if k in {
                "id", "listing_id", "match_id", "status", "created_at", "resolved_at", "resolved_by", "request_id"}}


class InvalidInput(ValueError):
    pass


def guarded(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        try:
            return view(*args, **kwargs)
        except repository.ProposalNotFound:
            return JsonResponse({"error": "Recurso no encontrado."}, status=404)
        except repository.DecisionConflict:
            return JsonResponse({"error": "La operación es incompatible con el estado actual."}, status=409)
        except (InvalidInput, InvalidQuery):
            return JsonResponse({"error": "Los datos no son válidos."}, status=400)
        except Exception as error:
            logger.error("Falló la operación de selección (%s).", type(error).__name__)
            return JsonResponse({"error": "No se pudo completar la operación."}, status=500)
    return wrapped


def body(request, fields):
    if request.content_type != "application/json":
        raise InvalidInput()
    try:
        data = json.loads(request.body)
    except (ValueError, UnicodeDecodeError, RecursionError):
        raise InvalidInput() from None
    if not isinstance(data, dict) or set(data) != set(fields):
        raise InvalidInput()
    return data


@never_cache
@require_http_methods(["GET", "POST"])
@firebase_role("BUYER", "SELLER")
@guarded
def proposals(request):
    user = request.user
    if request.method == "GET":
        limit, position = parse_query(request.GET, user.uid, salt=SALT + user.role)
        records = repository.get_proposals(user.uid, user.role, limit=limit + 1, position=position)
        return JsonResponse(page_result([payload(r) for r in records], limit, user.uid, salt=SALT + user.role))
    if user.role != "SELLER":
        return JsonResponse({"error": "Solo el vendedor puede proponer."}, status=403)
    data = body(request, {"listing_id", "match_id", "request_id"})
    if not all(valid_document_id(data[k]) for k in data) or len(data["request_id"]) > 128:
        raise InvalidInput()
    result, created = repository.create_proposal(user.uid, **data)
    return JsonResponse(payload(result), status=201 if created else 200)


@never_cache
@require_http_methods(["GET"])
@firebase_role("BUYER", "SELLER")
@guarded
def proposal_detail(request, proposal_id):
    if not valid_document_id(proposal_id):
        raise repository.ProposalNotFound()
    data, listing = repository.get_proposal(request.user.uid, request.user.role, proposal_id)
    seller = repository.get_user_profile(data["seller_uid"])
    result = payload(data)
    result["listing"] = {**listing_item(data["listing_id"], listing),
                         "availability": repository.listing_availability(listing),
                         "closure_reason": repository.listing_closure_reason(listing)}
    result["seller"] = {"id": data["seller_uid"], "name": seller["name"] if seller else ""}
    return JsonResponse(result)


@never_cache
@require_http_methods(["POST"])
@firebase_role("BUYER", "SELLER")
@guarded
def proposal_resolution(request, proposal_id, action):
    statuses = {"aceptar": ("BUYER", "ACCEPTED"), "rechazar": ("BUYER", "REJECTED"), "cancelar": ("SELLER", "CANCELLED")}
    if action not in statuses:
        raise repository.ProposalNotFound()
    role, status = statuses[action]
    if request.user.role != role:
        return JsonResponse({"error": "El rol no permite esta operación."}, status=403)
    body(request, set())
    if not valid_document_id(proposal_id):
        raise repository.ProposalNotFound()
    return JsonResponse(payload(repository.resolve_proposal(request.user.uid, role, proposal_id, status)))


from .management_views import edit_listing


@never_cache
@require_http_methods(["PUT"])
@firebase_role("SELLER")
@guarded
def availability(request, listing_id):
    if not valid_document_id(listing_id):
        raise repository.ProposalNotFound()
    data = body(request, {"availability"})
    if not isinstance(data["availability"], str) or data["availability"] not in {"ACTIVE", "PAUSED"}:
        raise InvalidInput()
    listing = repository.update_listing(request.user.uid, listing_id, data)
    return JsonResponse({"id": listing_id, "availability": repository.listing_availability(listing)})

