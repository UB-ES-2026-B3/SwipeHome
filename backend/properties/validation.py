from decimal import Decimal, InvalidOperation
from io import BytesIO
import re
import warnings
from pathlib import Path

from PIL import Image, UnidentifiedImageError
from PIL.Image import DecompressionBombError, DecompressionBombWarning

FIELD_ALIASES = {
    "title": ("title", "titulo"),
    "street": ("street", "calle"),
    "city": ("city", "localidad", "ciudad"),
    "postal_code": ("postal_code", "codigo_postal", "codigoPostal"),
    "description": ("description", "descripcion"),
    "price": ("price", "precio"),
    "surface": ("surface", "superficie"),
    "bedrooms": ("bedrooms", "dormitorios"),
    "bathrooms": ("bathrooms", "banos", "baños"),
    "people": ("people", "personas"),
    "shared_accommodation": (
        "shared_accommodation",
        "alojamiento_compartido",
        "compartido",
    ),
}


def _value(data, names):
    present = [data[name] for name in names if name in data]
    if present:
        first = present[0]
        if any(value != first for value in present[1:]):
            return _CONFLICT
        return first
    return None


_CONFLICT = object()


def _required_text(value):
    return isinstance(value, str) and bool(value.strip())


def _decimal(value, field, errors, max_decimal_places=2):
    if isinstance(value, bool) or value is None or (isinstance(value, str) and not value.strip()):
        errors[field] = "Campo obligatorio y numérico."
        return None
    try:
        parsed = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        errors[field] = "Debe ser un número mayor que cero."
        return None
    if (
        not parsed.is_finite()
        or parsed <= 0
        or -parsed.as_tuple().exponent > max_decimal_places
        or len(parsed.as_tuple().digits) - max(0, parsed.as_tuple().exponent) > 10
    ):
        errors[field] = "Debe ser un número mayor que cero."
        return None
    return parsed


def _integer(value, field, minimum, errors):
    if isinstance(value, bool) or value is None or (isinstance(value, str) and not value.strip()):
        errors[field] = "Campo obligatorio y entero."
        return None
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        errors[field] = "Debe ser un número entero válido."
        return None
    if not re.fullmatch(r"[+]?\d+", str(value).strip()) or parsed < minimum:
        errors[field] = f"Debe ser un entero igual o mayor que {minimum}."
        return None
    return parsed


def validate_property(data):
    errors = {}
    values = {field: _value(data, aliases) for field, aliases in FIELD_ALIASES.items()}
    for field, value in values.items():
        if value is _CONFLICT:
            errors[field] = "No se pueden mezclar valores contradictorios."
            values[field] = None

    for field in ("title", "street", "city", "postal_code", "description"):
        if not _required_text(values[field]):
            errors[field] = "Campo obligatorio y no vacío."
        else:
            values[field] = values[field].strip()

    values["price"] = _decimal(values["price"], "price", errors)
    values["surface"] = _decimal(values["surface"], "surface", errors)
    values["bedrooms"] = _integer(values["bedrooms"], "bedrooms", 0, errors)
    values["bathrooms"] = _integer(values["bathrooms"], "bathrooms", 1, errors)
    values["people"] = _integer(values["people"], "people", 1, errors)

    shared = values["shared_accommodation"]
    if shared not in ("Sí", "sí", "Si", "si", "No", "no", "SI", "NO"):
        errors["shared_accommodation"] = "Selecciona Sí o No."
    else:
        values["shared_accommodation"] = shared.lower() in ("sí", "si")

    return values, errors


MAX_PHOTOS = 10
MAX_PHOTO_SIZE = 5 * 1024 * 1024
ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


def photo_uploads(data):
    """Devuelve las fotografías multipart usando aliases de integración."""
    for name in ("photos", "fotografias", "images", "photos[]", "fotografias[]"):
        photos = data.getlist(name)
        if photos:
            return photos
    return []


def validate_photos(photos):
    errors = {}
    if not photos:
        return {"photos": "Se requiere al menos una fotografía."}
    if len(photos) > MAX_PHOTOS:
        return {"photos": "Se permiten como máximo 10 fotografías."}
    for index, photo in enumerate(photos):
        if getattr(photo, "size", 0) > MAX_PHOTO_SIZE:
            errors[f"photos[{index}]"] = "Cada fotografía puede ocupar como máximo 5 MB."
            continue
        if Path(getattr(photo, "name", "")).suffix.lower() not in ALLOWED_EXTENSIONS:
            errors[f"photos[{index}]"] = "La extensión de la fotografía no está permitida."
            continue
        content = photo.read()
        photo.seek(0)
        content_type = getattr(photo, "content_type", None)
        valid = False
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", DecompressionBombWarning)
                with Image.open(BytesIO(content)) as image:
                    valid = image.format in {"JPEG", "PNG", "WEBP"} and image.format == {
                        "image/jpeg": "JPEG",
                        "image/png": "PNG",
                        "image/webp": "WEBP",
                    }.get(content_type)
                    if valid:
                        image.verify()
        except (DecompressionBombError, UnidentifiedImageError, OSError, ValueError):
            valid = False
        except DecompressionBombWarning:
            valid = False
        if not valid:
            errors[f"photos[{index}]"] = "El contenido de la fotografía no es válido."
    return errors
