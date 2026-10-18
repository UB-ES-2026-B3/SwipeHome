from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET


@never_cache
@require_GET
def health(request):
    """Comprobacion de vida del servicio.

    No toca la base de datos a proposito: sirve para saber si el proceso
    de Django esta levantado en Render, incluso mientras la capa de datos
    esta en migracion.
    """
    return JsonResponse({"status": "ok"})
