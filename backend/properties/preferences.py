"""Validación y evaluación de preferencias del explorador."""
import hashlib
import json
import re
from decimal import Decimal, InvalidOperation


DEFAULT_FILTERS = {
    "price_min": None,
    "price_max": None,
    "surface_min": None,
    "surface_max": None,
    "bedrooms_min": None,
    "bathrooms_min": None,
    "people_min": None,
    "shared_accommodation": None,
}

_DECIMAL_FIELDS = {
    "price_min": "price_min_cents",
    "price_max": "price_max_cents",
    "surface_min": "surface_min_hundredths",
    "surface_max": "surface_max_hundredths",
}
_INTEGER_FIELDS = {
    "bedrooms_min": "bedrooms_min",
    "bathrooms_min": "bathrooms_min",
    "people_min": "people_min",
}
_STORED_KEYS = (
    "price_min_cents",
    "price_max_cents",
    "surface_min_hundredths",
    "surface_max_hundredths",
    "bedrooms_min",
    "bathrooms_min",
    "people_min",
    "shared_accommodation",
)


class InvalidPreferences(ValueError):
    def __init__(self, errors):
        self.errors = errors
        super().__init__("Preferencias inválidas.")


def _decimal_filter(value, field, errors):
    if value is None:
        return None
    if isinstance(value, bool):
        errors[field] = "Introduce un número válido."
        return None
    try:
        parsed = Decimal(str(value).strip())
    except (InvalidOperation, ValueError, AttributeError):
        errors[field] = "Introduce un número válido."
        return None
    if (
        not parsed.is_finite()
        or parsed < 0
        or -parsed.as_tuple().exponent > 2
        or len(parsed.as_tuple().digits) - max(0, parsed.as_tuple().exponent) > 10
    ):
        errors[field] = "Usa un número no negativo con hasta dos decimales."
        return None
    return int(parsed * 100)


def _integer_filter(value, field, errors):
    if value is None:
        return None
    if isinstance(value, bool):
        errors[field] = "Introduce un número entero no negativo."
        return None
    text = str(value).strip()
    if not re.fullmatch(r"\d{1,9}", text):
        errors[field] = "Introduce un número entero no negativo."
        return None
    return int(text)


def validate_filters(payload):
    if not isinstance(payload, dict) or set(payload) != set(DEFAULT_FILTERS):
        raise InvalidPreferences({"filters": "Envía todos los campos de filtros permitidos."})

    errors = {}
    stored = {}
    for api_field, stored_field in _DECIMAL_FIELDS.items():
        stored[stored_field] = _decimal_filter(payload[api_field], api_field, errors)
    for field, stored_field in _INTEGER_FIELDS.items():
        stored[stored_field] = _integer_filter(payload[field], field, errors)

    shared = payload["shared_accommodation"]
    if shared is not None and not isinstance(shared, bool):
        errors["shared_accommodation"] = "Selecciona Sí, No o Sin restricción."
    stored["shared_accommodation"] = shared if isinstance(shared, bool) else None

    for low, high in (
        ("price_min_cents", "price_max_cents"),
        ("surface_min_hundredths", "surface_max_hundredths"),
    ):
        if stored[low] is not None and stored[high] is not None and stored[low] > stored[high]:
            errors[_api_key(low)] = "El mínimo no puede superar el máximo."
            errors[_api_key(high)] = "El máximo debe ser igual o mayor que el mínimo."

    if errors:
        raise InvalidPreferences(errors)
    return stored


def validate_stored_filters(stored):
    if not isinstance(stored, dict) or set(stored) != set(_STORED_KEYS):
        raise ValueError("Preferencias almacenadas incompletas.")
    for key in _STORED_KEYS[:-1]:
        value = stored[key]
        if value is not None and (
            isinstance(value, bool) or not isinstance(value, int) or value < 0
        ):
            raise ValueError("Preferencias almacenadas no válidas.")
    if stored["shared_accommodation"] is not None and not isinstance(
        stored["shared_accommodation"], bool
    ):
        raise ValueError("Preferencias almacenadas no válidas.")
    for low, high in (
        ("price_min_cents", "price_max_cents"),
        ("surface_min_hundredths", "surface_max_hundredths"),
    ):
        if (
            stored[low] is not None and stored[high] is not None
            and stored[low] > stored[high]
        ):
            raise ValueError("Preferencias almacenadas no válidas.")
    return dict(stored)


def _api_key(stored_key):
    for api_key, internal_key in _DECIMAL_FIELDS.items():
        if internal_key == stored_key:
            return api_key
    return stored_key


def filters_to_api(stored):
    validate_stored_filters(stored)
    filters = {}
    for api_field, stored_field in _DECIMAL_FIELDS.items():
        value = stored.get(stored_field)
        filters[api_field] = None if value is None else f"{Decimal(value) / 100:.2f}"
    for field, stored_field in _INTEGER_FIELDS.items():
        filters[field] = stored.get(stored_field)
    filters["shared_accommodation"] = stored.get("shared_accommodation")
    return filters


def filter_salt(stored):
    fingerprint = hashlib.sha256(
        json.dumps(stored, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return f"properties.explore.v1.{fingerprint}"


def matches_filters(listing, filters):
    for field, stored_field in _DECIMAL_FIELDS.items():
        bound = filters.get(stored_field)
        if bound is None:
            continue
        listing_field = "price_cents" if field.startswith("price_") else "surface_hundredths"
        value = listing.get(listing_field)
        if not isinstance(value, int):
            return False
        if field.endswith("_min") and value < bound:
            return False
        if field.endswith("_max") and value > bound:
            return False

    for field, stored_field in _INTEGER_FIELDS.items():
        minimum = filters.get(stored_field)
        if minimum is not None:
            value = listing.get(field.removesuffix("_min"))
            if not isinstance(value, int) or value < minimum:
                return False

    shared = filters.get("shared_accommodation")
    return shared is None or listing.get("shared_accommodation") is shared
