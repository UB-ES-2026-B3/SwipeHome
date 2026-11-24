"""Contrato público del anuncio; nunca serializar el documento completo."""
from decimal import Decimal

from accounts.pagination import timestamp

TEXT_FIELDS = ("title", "street", "city", "postal_code", "description")
INTEGER_MINIMUMS = {"price_cents": 1, "surface_hundredths": 1, "bedrooms": 0,
                    "bathrooms": 1, "people": 1}


def published_listing(data):
    """Mismo esquema que create_listing; los documentos parciales no se publican."""
    if not isinstance(data, dict) or data.get("published") is not True:
        return False
    if not all(isinstance(data.get(k), str) and data[k].strip()
               for k in (*TEXT_FIELDS, "seller_uid")):
        return False
    if not all(type(data.get(k)) is int and data[k] >= minimum
               for k, minimum in INTEGER_MINIMUMS.items()):
        return False
    photos = data.get("photos")
    if not isinstance(photos, list) or not 1 <= len(photos) <= 10:
        return False
    if not all(isinstance(photo, str) and photo.strip() for photo in photos):
        return False
    if type(data.get("shared_accommodation")) is not bool:
        return False
    try:
        timestamp(data["created_at"])
    except (KeyError, TypeError, AttributeError, ValueError):
        return False
    return True


def listing_item(identifier, data):
    return {
        "id": identifier,
        **{field: data[field] for field in TEXT_FIELDS},
        "price": str((Decimal(data["price_cents"]) / 100).quantize(Decimal("0.00"))),
        "surface": str((Decimal(data["surface_hundredths"]) / 100).quantize(Decimal("0.00"))),
        **{field: data[field] for field in ("bedrooms", "bathrooms", "people", "shared_accommodation")},
        "photos": list(data["photos"]),
        "created_at": timestamp(data["created_at"]),
    }
