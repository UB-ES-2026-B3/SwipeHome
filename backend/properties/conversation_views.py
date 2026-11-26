"""API privada de conversaciones entre participantes de un match confirmado."""
import json
import logging
import re
from functools import wraps
from uuid import UUID

from django.core.exceptions import RequestDataTooBig
from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from accounts import repository
from accounts.authentication import firebase_roles
from accounts.pagination import InvalidQuery, page_result, parse_query, valid_document_id

logger = logging.getLogger(__name__)
CURSOR_SALT = "properties.conversations.v1"


def conversation_endpoint(*methods):
    def decorate(view):
        @never_cache
        @require_http_methods(methods)
        @firebase_roles("BUYER", "SELLER")
        @wraps(view)
        def wrapped(request, **kwargs):
            try:
                if any(not valid_document_id(value) for value in kwargs.values()):
                    raise repository.MatchNotFound()
                return view(request, **kwargs)
            except (InvalidQuery, RequestDataTooBig):
                return JsonResponse({"error": "Los datos o parámetros no son válidos."}, status=400)
            except repository.MatchNotFound:
                return JsonResponse({"error": "Recurso no encontrado."}, status=404)
            except repository.DecisionConflict:
                return JsonResponse({"error": "El estado del match o del envío impide la operación."}, status=409)
            except Exception as error:
                logger.error("Falló una operación de conversación (%s).", type(error).__name__)
                return JsonResponse({"error": "No se pudo completar la operación."}, status=500)
        return wrapped
    return decorate


def json_object(request, fields):
    if request.content_type != "application/json":
        raise InvalidQuery()
    try:
        body = json.loads(request.body)
    except (ValueError, RecursionError):
        raise InvalidQuery() from None
    if not isinstance(body, dict) or set(body) != fields:
        raise InvalidQuery()
    return body


def message_page(params):
    if (
        set(params) - {"limit", "before", "after"}
        or {"before", "after"} <= set(params)
        or any(len(params.getlist(key)) != 1 for key in params)
    ):
        raise InvalidQuery()
    values = {}
    for key, value in params.items():
        if not re.fullmatch(r"[0-9]{1,19}", value):
            raise InvalidQuery()
        values[key] = int(value)
    limit = values.get("limit", 50)
    before, after = values.get("before"), values.get("after")
    if not 1 <= limit <= 100 or before == 0 or max(before or 0, after or 0) >= 2**63:
        raise InvalidQuery()
    return limit, before, after


def message_payload(request):
    body = json_object(request, {"client_message_id", "content"})
    key, content = body["client_message_id"], body["content"]
    if not isinstance(key, str) or not re.fullmatch(
        r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", key
    ):
        raise InvalidQuery()
    if not isinstance(content, str) or not 1 <= len(content) <= 2000 or not content.strip():
        raise InvalidQuery()
    try:
        content.encode("utf-8")
    except UnicodeEncodeError:
        raise InvalidQuery() from None
    return str(UUID(key)), content


@conversation_endpoint("POST")
def open_conversation(request, match_id):
    json_object(request, set())
    conversation, created = repository.open_conversation(request.user, match_id)
    return JsonResponse(conversation, status=201 if created else 200)


@conversation_endpoint("GET")
def conversation_list(request):
    uid = request.user.uid
    limit, position = parse_query(request.GET, uid, salt=CURSOR_SALT, timestamp_field="updated_at")
    records = repository.get_conversations(request.user, limit=limit + 1, position=position)
    for record in records:
        del record["created_at"]
    return JsonResponse(page_result(records, limit, uid, salt=CURSOR_SALT, timestamp_field="updated_at"))


@conversation_endpoint("GET")
def conversation_detail(request, conversation_id):
    return JsonResponse(repository.get_conversation(request.user, conversation_id))


@conversation_endpoint("GET", "POST")
def conversation_messages(request, conversation_id):
    if request.method == "POST":
        key, content = message_payload(request)
        message, created = repository.send_conversation_message(request.user, conversation_id, key, content)
        return JsonResponse(message, status=201 if created else 200)

    limit, before, after = message_page(request.GET)
    messages = repository.get_conversation_messages(
        request.user, conversation_id, limit=limit + 1, before=before, after=after,
    )
    page = messages[:limit]
    continuation = page[-1]["sequence"] if len(messages) > limit else None
    if after is None:
        page.reverse()
    return JsonResponse({
        "items": page,
        "next_before": continuation if after is None else None,
        "next_after": continuation if after is not None else None,
    })

