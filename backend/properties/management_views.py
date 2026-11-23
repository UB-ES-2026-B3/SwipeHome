"""US10: consulta, edición y gestión de disponibilidad de anuncios propios."""
import json
import logging
from functools import wraps

from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from accounts import repository
from accounts.authentication import firebase_role
from accounts.pagination import InvalidQuery, timestamp, valid_document_id
from .serialization import listing_item
from .validation import photo_uploads, validate_photos, validate_property

logger = logging.getLogger(__name__)


class InvalidInput(ValueError):
    pass


def guarded(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        try:
            return view(*args, **kwargs)
        except (repository.ProposalNotFound, repository.ListingNotFound):
            return JsonResponse({"error": "Recurso no encontrado."}, status=404)
        except repository.DecisionConflict:
            return JsonResponse({"error": "La operación es incompatible con el estado actual."}, status=409)
        except repository.InvalidPhotos as photo_err:
            return JsonResponse({"errors": {"photos": str(photo_err)}}, status=400)
        except (InvalidInput, InvalidQuery):
            return JsonResponse({"error": "Los datos no son válidos."}, status=400)
        except Exception as error:
            logger.error("Falló la operación de gestión (%s).", type(error).__name__)
            return JsonResponse({"error": "No se pudo completar la operación."}, status=500)
    return wrapped


def _extract_version_from_body(request):
    if not request.body:
        return None
    if request.content_type != "application/json":
        return None
    try:
        data = json.loads(request.body)
        if not isinstance(data, dict):
            raise InvalidInput("Se requiere un objeto JSON.")
        version = data.get("version")
        if version is not None:
            if isinstance(version, int) and version >= 1:
                return version
            if isinstance(version, str) and version.isdigit():
                return int(version)
            raise InvalidInput("Versión inválida.")
        return None
    except json.JSONDecodeError:
        raise InvalidInput("JSON malformado.")


@never_cache
@require_http_methods(["GET"])
@firebase_role("SELLER")
@guarded
def my_listings(request):
    """GET /api/inmuebles/mios: publicaciones propias del vendedor con estado y acciones."""
    records = repository.get_seller_management_listings(request.user.uid)
    return JsonResponse({"items": records, "properties": records}, status=200)


@never_cache
@require_http_methods(["GET"])
@firebase_role("SELLER")
@guarded
def listing_management_detail(request, listing_id):
    """GET /api/inmuebles/{id}/gestion: detalle de un anuncio propio para gestionarlo."""
    if not valid_document_id(listing_id):
        raise repository.ProposalNotFound()
    detail = repository.get_listing_for_management(request.user.uid, listing_id)
    return JsonResponse(detail, status=200)


@never_cache
@require_http_methods(["PATCH"])
@firebase_role("SELLER")
@guarded
def edit_listing(request, listing_id):
    """PATCH /api/inmuebles/{id}: modificar datos y fotografías con control de versión."""
    if not valid_document_id(listing_id):
        raise repository.ProposalNotFound()

    expected_version = None
    new_photos = None
    retained_photos = None
    existing_edit_data = None

    if request.content_type == "application/json":
        try:
            data = json.loads(request.body)
        except (ValueError, UnicodeDecodeError, RecursionError):
            raise InvalidInput()
        if not isinstance(data, dict):
            raise InvalidInput()

        # No se permite cambiar identificador ni propietario
        if "id" in data and str(data["id"]) != str(listing_id):
            return JsonResponse({"errors": {"id": "No se permite cambiar el identificador."}}, status=400)
        if "seller_uid" in data and str(data["seller_uid"]) != str(request.user.uid):
            return JsonResponse({"errors": {"seller_uid": "No se permite cambiar el propietario."}}, status=400)
        if "owner" in data and str(data["owner"]) != str(request.user.uid):
            return JsonResponse({"errors": {"owner": "No se permite cambiar el propietario."}}, status=400)
        if "propietario" in data and str(data["propietario"]) != str(request.user.uid):
            return JsonResponse({"errors": {"propietario": "No se permite cambiar el propietario."}}, status=400)

        if "version" in data:
            v = data["version"]
            if isinstance(v, int) and v >= 1:
                expected_version = v
            elif isinstance(v, str) and v.isdigit():
                expected_version = int(v)
            else:
                return JsonResponse({"errors": {"version": "Versión inválida."}}, status=400)

        if "photos" in data:
            photos_val = data["photos"]
            if not isinstance(photos_val, list) or not photos_val:
                return JsonResponse({"errors": {"photos": "La edición no puede dejar el anuncio sin imágenes válidas."}}, status=400)
            if any(not isinstance(p, str) or not p.strip() for p in photos_val):
                return JsonResponse({"errors": {"photos": "Formato de fotografía inválido."}}, status=400)
            if len(photos_val) > 10:
                return JsonResponse({"errors": {"photos": "Se permiten como máximo 10 fotografías."}}, status=400)
            retained_photos = photos_val

        existing = repository.get_listing(listing_id)
        if not existing or existing.get("seller_uid") != request.user.uid:
            raise repository.ProposalNotFound()
        existing_edit_data = {
            "title": existing.get("title", ""),
            "street": existing.get("street", ""),
            "city": existing.get("city", ""),
            "postal_code": existing.get("postal_code", ""),
            "description": existing.get("description", ""),
            "price": str(existing.get("price_cents", 0) / 100),
            "surface": str(existing.get("surface_hundredths", 0) / 100),
            "bedrooms": existing.get("bedrooms", 0),
            "bathrooms": existing.get("bathrooms", 0),
            "people": existing.get("people", 0),
            "shared_accommodation": "Sí" if existing.get("shared_accommodation") else "No",
        }

        patch_data = {**existing_edit_data, **data}
        values, errors = validate_property(patch_data)
        if errors:
            return JsonResponse({"errors": errors}, status=400)
        values["price_cents"] = int(values.pop("price") * 100)
        values["surface_hundredths"] = int(values.pop("surface") * 100)

    elif request.content_type.startswith("multipart/form-data"):
        # Django only populates request.POST/FILES for POST; for PATCH we need
        # to parse manually when they are empty despite the body being present.
        if request.POST or request.FILES:
            post_data = request.POST
            files_data = request.FILES
        else:
            from django.http.multipartparser import MultiPartParser
            post_data, files_data = MultiPartParser(
                request.META, request, request.upload_handlers
            ).parse()
        data = post_data
        if "id" in data and str(data["id"]) != str(listing_id):
            return JsonResponse({"errors": {"id": "No se permite cambiar el identificador."}}, status=400)
        if "seller_uid" in data and str(data["seller_uid"]) != str(request.user.uid):
            return JsonResponse({"errors": {"seller_uid": "No se permite cambiar el propietario."}}, status=400)
        if "owner" in data and str(data["owner"]) != str(request.user.uid):
            return JsonResponse({"errors": {"owner": "No se permite cambiar el propietario."}}, status=400)
        if "propietario" in data and str(data["propietario"]) != str(request.user.uid):
            return JsonResponse({"errors": {"propietario": "No se permite cambiar el propietario."}}, status=400)

        if "version" in data:
            v = data["version"]
            if isinstance(v, int) and v >= 1:
                expected_version = v
            elif isinstance(v, str) and v.isdigit():
                expected_version = int(v)
            else:
                return JsonResponse({"errors": {"version": "Versión inválida."}}, status=400)

        retained_raw = (data.getlist("existing_photos") or
                        data.getlist("retained_photos") or
                        data.getlist("photos"))
        if not retained_raw and "existing_photos" in data:
            retained_raw = [data["existing_photos"]]
        if len(retained_raw) == 1 and retained_raw[0].strip().startswith("["):
            try:
                retained_raw = json.loads(retained_raw[0])
            except Exception:
                pass
        if retained_raw:
            retained_photos = [p for p in retained_raw if isinstance(p, str) and p.strip()]
        elif "existing_photos" in data or "retained_photos" in data:
            retained_photos = []

        new_photos = photo_uploads(files_data)
        errors = {}
        if new_photos:
            photo_errs = validate_photos(new_photos)
            if photo_errs:
                errors.update(photo_errs)

        if retained_photos is not None and not retained_photos and not new_photos:
            errors["photos"] = "La edición no puede dejar el anuncio sin imágenes válidas."
        if retained_photos is not None and (len(retained_photos) + len(new_photos)) > 10:
            errors["photos"] = "Se permiten como máximo 10 fotografías."

        if errors:
            return JsonResponse({"errors": errors}, status=400)
        existing = repository.get_listing(listing_id)
        if not existing or existing.get("seller_uid") != request.user.uid:
            raise repository.ProposalNotFound()
        existing_edit_data = {
            "title": existing.get("title", ""),
            "street": existing.get("street", ""),
            "city": existing.get("city", ""),
            "postal_code": existing.get("postal_code", ""),
            "description": existing.get("description", ""),
            "price": str(existing.get("price_cents", 0) / 100),
            "surface": str(existing.get("surface_hundredths", 0) / 100),
            "bedrooms": existing.get("bedrooms", 0),
            "bathrooms": existing.get("bathrooms", 0),
            "people": existing.get("people", 0),
            "shared_accommodation": "Sí" if existing.get("shared_accommodation") else "No",
        }
        patch_data = {**existing_edit_data, **{k: v for k, v in data.items()
                                             if k in {"title", "street", "city", "postal_code",
                                                      "description", "price", "surface", "bedrooms",
                                                      "bathrooms", "people", "shared_accommodation"}}}
        values, prop_errs = validate_property(patch_data)
        if prop_errs:
            errors.update(prop_errs)
            return JsonResponse({"errors": errors}, status=400)
        values["price_cents"] = int(values.pop("price") * 100)
        values["surface_hundredths"] = int(values.pop("surface") * 100)

    else:
        raise InvalidInput("Tipo de contenido no admitido.")

    listing = repository.update_listing_full(
        request.user.uid,
        listing_id,
        values,
        new_photos=new_photos,
        retained_photos=retained_photos,
        expected_version=expected_version,
    )
    result = listing_item(listing_id, listing)
    result["version"] = int(listing.get("version", 1))
    result["availability"] = repository.listing_availability(listing)
    result["closure_reason"] = repository.listing_closure_reason(listing)
    result["updated_at"] = timestamp(listing.get("updated_at")) if listing.get("updated_at") else None
    return JsonResponse(result, status=200)


@never_cache
@require_http_methods(["POST"])
@firebase_role("SELLER")
@guarded
def pause_listing(request, listing_id):
    """POST /api/inmuebles/{id}/pausar: pausar un anuncio activo."""
    if not valid_document_id(listing_id):
        raise repository.ProposalNotFound()
    expected_version = _extract_version_from_body(request)
    result = repository.pause_listing(request.user.uid, listing_id, expected_version=expected_version)
    return JsonResponse(result, status=200)


@never_cache
@require_http_methods(["POST"])
@firebase_role("SELLER")
@guarded
def reactivate_listing(request, listing_id):
    """POST /api/inmuebles/{id}/reactivar: reactivar un anuncio pausado."""
    if not valid_document_id(listing_id):
        raise repository.ProposalNotFound()
    expected_version = _extract_version_from_body(request)
    result = repository.reactivate_listing(request.user.uid, listing_id, expected_version=expected_version)
    return JsonResponse(result, status=200)


@never_cache
@require_http_methods(["POST"])
@firebase_role("SELLER")
@guarded
def withdraw_listing(request, listing_id):
    """POST /api/inmuebles/{id}/retirar: cerrar manualmente el anuncio."""
    if not valid_document_id(listing_id):
        raise repository.ProposalNotFound()
    expected_version = _extract_version_from_body(request)
    result = repository.withdraw_listing(request.user.uid, listing_id, expected_version=expected_version)
    return JsonResponse(result, status=200)
