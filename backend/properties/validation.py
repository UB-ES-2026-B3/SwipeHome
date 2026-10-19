from decimal import Decimal, InvalidOperation
import re


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
    for name in names:
        if name in data:
            return data[name]
    return None


def _required_text(value):
    return isinstance(value, str) and bool(value.strip())


def _decimal(value, field, errors, max_decimal_places=2):
    if not isinstance(value, str) or not value.strip():
        errors[field] = "Campo obligatorio y numérico."
        return None
    try:
        parsed = Decimal(value)
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
    if not isinstance(value, str) or not value.strip():
        errors[field] = "Campo obligatorio y entero."
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        errors[field] = "Debe ser un número entero válido."
        return None
    if not re.fullmatch(r"[+]?\d+", value.strip()) or parsed < minimum:
        errors[field] = f"Debe ser un entero igual o mayor que {minimum}."
        return None
    return parsed


def validate_property(data):
    errors = {}
    values = {field: _value(data, aliases) for field, aliases in FIELD_ALIASES.items()}

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
