"""Consulta de notificaciones sin efectos de escritura."""
import logging
from types import SimpleNamespace

from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from . import repository
from .authentication import AuthenticationFailed, verified_session
from .notification_service import InvalidNotificationQuery, list_notifications

logger = logging.getLogger(__name__)


@never_cache
@require_GET
def notifications(request):
    try:
        session = verified_session(request)
        profile = repository.get_user_profile(session["uid"])
        if profile is None or profile["role"] not in {"BUYER", "SELLER"}:
            return JsonResponse({"error": "La cuenta no tiene acceso a los avisos."}, status=403)
        # Identidad creada solo con el token verificado y el rol del servidor.
        # No requiere ORM, sesiones Django ni identificadores enviados por el cliente.
        request.user = SimpleNamespace(uid=session["uid"], role=profile["role"], is_authenticated=True)
        try:
            result = list_notifications(request.user, request.GET)
        except InvalidNotificationQuery:
            return JsonResponse({"error": "Los parámetros de consulta no son válidos."}, status=400)
        return JsonResponse(result)
    except AuthenticationFailed:
        response = JsonResponse({"error": "No hay una sesión autenticada."}, status=401)
        response["WWW-Authenticate"] = "Bearer"
        return response
    except Exception as error:
        logger.error("Falló la consulta de notificaciones (%s).", type(error).__name__)
        return JsonResponse({"error": "No se pudieron consultar los avisos. Inténtalo de nuevo."}, status=500)
