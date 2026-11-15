"""API privada de preferencias US8, Firebase Bearer."""
import json
import logging
from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_http_methods
from accounts import repository
from accounts.authentication import firebase_role
from .preferences import validate_preferences

logger = logging.getLogger(__name__)


@never_cache
@require_http_methods(["GET", "PUT", "DELETE"])
@firebase_role("BUYER")
def preferences(request):
    if request.GET:
        return JsonResponse({"error": "Parámetros no permitidos."}, status=400)
    values = None
    if request.method == "PUT":
        if request.content_type != "application/json":
            return JsonResponse({"errors": {"body": "Se requiere application/json."}}, status=400)
        try:
            body = json.loads(request.body)
            values, errors = validate_preferences(body)
        except (ValueError, UnicodeDecodeError, RecursionError):
            errors = {"body": "JSON inválido."}
        if errors:
            return JsonResponse({"errors": errors}, status=400)
    elif request.method == "DELETE":
        values, _ = validate_preferences({})
    try:
        if values is None:
            values = repository.get_search_preferences(request.user.uid)
        else:
            values = repository.save_search_preferences(request.user.uid, values)
        return JsonResponse(values)
    except Exception as error:
        logger.error("Fallaron preferencias (%s).", type(error).__name__)
        return JsonResponse({"error": "No se pudieron consultar o guardar las preferencias."}, status=500)


@never_cache
@require_GET
@firebase_role("BUYER")
def filter_options(request):
    if request.GET:
        return JsonResponse({"error": "Parámetros no permitidos."}, status=400)
    try:
        return JsonResponse({"cities": repository.get_filter_cities()})
    except Exception as error:
        logger.error("Fallaron localidades (%s).", type(error).__name__)
        return JsonResponse({"error": "No se pudieron consultar las localidades."}, status=500)
