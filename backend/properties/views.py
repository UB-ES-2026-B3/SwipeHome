import logging

from django.core.files.storage import default_storage
from django.db import transaction
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from .models import Property, PropertyPhoto
from .storage import MAX_PHOTOS, generated_name, validate_photo
from .validation import validate_property

logger = logging.getLogger(__name__)


def _photos(request):
    for field in ("photos", "fotografias", "images", "photos[]"):
        photos = request.FILES.getlist(field)
        if photos:
            return photos
    return []


@require_http_methods(["POST"])
def create_property(request):
    if not request.user.is_authenticated:
        return JsonResponse({"error": "Se requiere una sesión autenticada."}, status=401)
    if request.user.role != "SELLER":
        return JsonResponse({"error": "Solo los vendedores pueden publicar inmuebles."}, status=403)
    if not request.content_type.startswith("multipart/form-data"):
        return JsonResponse({"error": "Se requiere multipart/form-data."}, status=400)

    values, errors = validate_property(request.POST)
    photos = _photos(request)
    if not photos:
        errors["photos"] = "Se requiere al menos una fotografía."
    elif len(photos) > MAX_PHOTOS:
        errors["photos"] = "Se permiten como máximo 10 fotografías."
    else:
        for index, photo in enumerate(photos):
            try:
                validate_photo(photo)
            except ValueError as error:
                errors[f"photos[{index}]"] = str(error)
    if errors:
        return JsonResponse({"errors": errors}, status=400)

    saved_paths = []
    completed = False
    try:
        with transaction.atomic():
            property_instance = Property.objects.create(
                **values,
                seller=request.user,
                published=False,
            )
            for position, photo in enumerate(photos):
                name = generated_name(photo)
                stored_name = default_storage.save(name, photo)
                saved_paths.append(stored_name)
                PropertyPhoto.objects.create(
                    property=property_instance,
                    file=stored_name,
                    position=position,
                )
            property_instance.published = True
            property_instance.published_at = timezone.now()
            property_instance.save(update_fields=["published", "published_at"])
        completed = True
        return JsonResponse({"id": property_instance.pk}, status=201)
    except Exception:
        logger.error("No se pudo completar la publicación del inmueble.")
        return JsonResponse(
            {"error": "No se pudo completar la publicación. Inténtalo de nuevo."},
            status=500,
        )
    finally:
        if not completed:
            for path in saved_paths:
                try:
                    default_storage.delete(path)
                except Exception:
                    logger.error("No se pudo limpiar un archivo de publicación.")
