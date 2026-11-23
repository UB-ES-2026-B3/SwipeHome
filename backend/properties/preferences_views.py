"""API de preferencias privadas del explorador para Compradores."""
import json
import logging

from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from accounts.authentication import firebase_role
from .discovery_service import get_filters, save_filters
from .preferences import InvalidPreferences

logger = logging.getLogger(__name__)


@never_cache
@require_http_methods(["GET", "PUT"])
@firebase_role("BUYER")
def buyer_preferences(request):
    if request.method == "GET":
        try:
            return JsonResponse({"filters": get_filters(request.user)})
        except Exception as error:
            logger.error("Falló la consulta de preferencias (%s).", type(error).__name__)
            return JsonResponse({"error": "No se pudieron consultar los filtros."}, status=500)

    if request.content_type != "application/json":
        return JsonResponse({"error": "Se requiere application/json."}, status=400)
    try:
        body = json.loads(request.body)
    except (ValueError, UnicodeDecodeError, RecursionError):
        return JsonResponse({"error": "El formato de filtros no es válido."}, status=400)

    try:
        filters = save_filters(request.user, body)
        return JsonResponse({"filters": filters, "message": "Filtros guardados correctamente."})
    except InvalidPreferences as error:
        return JsonResponse({"errors": error.errors}, status=400)
    except Exception as error:
        logger.error("Falló el guardado de preferencias (%s).", type(error).__name__)
        return JsonResponse(
            {"error": "No se pudieron guardar los filtros. Inténtalo de nuevo."},
            status=500,
        )
