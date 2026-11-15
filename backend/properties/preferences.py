"""Validación canónica US8 y comparación exacta con el esquema US3."""
import hashlib
import json
import re
from decimal import Decimal, InvalidOperation

FIELDS = ("city", "postal_code", "min_price", "max_price", "min_area", "max_area",
          "bedrooms", "min_bathrooms", "people_offered", "is_shared")


def validate_preferences(body):
    values = dict.fromkeys(FIELDS)
    if not isinstance(body, dict):
        return values, {"body": "Se requiere un objeto JSON."}
    errors = {key: "Campo desconocido." for key in body if key not in FIELDS}
    for key in FIELDS:
        value = body.get(key)
        if value is None:
            continue
        if key in ("city", "postal_code"):
            if not isinstance(value, str):
                errors[key] = "Debe ser texto o null."
            else:
                values[key] = value.strip() or None
        elif key == "is_shared":
            if type(value) is not bool:
                errors[key] = "Debe ser booleano o null."
            else:
                values[key] = value
        elif key in ("bedrooms", "min_bathrooms", "people_offered"):
            minimum = 0 if key == "bedrooms" else 1
            if type(value) is not int or not minimum <= value <= 9223372036854775807:
                errors[key] = f"Debe ser entero >= {minimum}."
            else:
                values[key] = value
        else:
            try:
                if (
                    not isinstance(value, str) or not value.strip() or len(value) > 100
                    or not re.fullmatch(r"[+]?[0-9]+(?:\.[0-9]+)?", value.strip())
                ):
                    raise ValueError()
                number = Decimal(value.strip())
                if (not number.is_finite() or number < 0 or
                    (number == 0 and key != "min_price") or
                    ("price" in key and number.as_tuple().exponent < -2) or
                    ("area" in key and number.as_tuple().exponent < -2)):
                    raise ValueError()
                canonical = format(number, ".2f")
                if len(canonical) > 100:
                    raise ValueError()
                values[key] = canonical
            except (ValueError, InvalidOperation):
                errors[key] = "Debe ser una cadena decimal válida, con hasta dos decimales y el signo permitido por el campo."
    for low, high in (("min_price", "max_price"), ("min_area", "max_area")):
        if values[low] is not None and values[high] is not None:
            if Decimal(values[low]) > Decimal(values[high]):
                errors[high] = "Debe ser mayor o igual al mínimo."
    return values, errors


def fingerprint(values):
    return hashlib.sha256(json.dumps(values, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def matches_preferences(data, values):
    for key, field in (("city", "city"), ("postal_code", "postal_code"),
                       ("bedrooms", "bedrooms"), ("people_offered", "people"),
                       ("is_shared", "shared_accommodation")):
        expected = values.get(key)
        actual = data[field].strip() if key in ("city", "postal_code") else data[field]
        if expected is not None and actual != expected:
            return False
    if values.get("min_bathrooms") is not None and data["bathrooms"] < values["min_bathrooms"]:
        return False
    for suffix, field in (("price", "price_cents"), ("area", "surface_hundredths")):
        for prefix in ("min", "max"):
            value = values.get(prefix + "_" + suffix)
            if value is not None:
                bound = int(value.replace(".", ""))
                if (prefix == "min" and data[field] < bound) or (prefix == "max" and data[field] > bound):
                    return False
    return True
