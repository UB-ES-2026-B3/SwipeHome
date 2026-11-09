"""Consulta privada de avisos del propietario, sin escrituras."""
import logging

from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from .authentication import firebase_auth
from .notification_service import InvalidNotificationQuery, list_notifications

logger = logging.getLogger(__name__)


@never_cache
@require_GET
@firebase_auth
def notifications(request):
    try:
        return JsonResponse(list_notifications(request.user, request.GET))
    except InvalidNotificationQuery:
        return JsonResponse({"error": "Los parámetros de consulta no son válidos."}, status=400)
    except Exception as error:
        logger.error("Falló la consulta de notificaciones (%s).", type(error).__name__)
        return JsonResponse({"error": "No se pudieron consultar los avisos. Inténtalo de nuevo."}, status=500)
