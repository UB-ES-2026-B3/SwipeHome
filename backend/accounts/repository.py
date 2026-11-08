"""Único módulo del proyecto que habla con Firestore y Firebase Storage.

Las vistas llaman aquí, nunca a Firestore directamente. Si algún día se cambia
de base de datos, se reescribe este fichero y nada más.

Los campos name/email del documento son la instantánea del registro.
El nombre y email vigentes proceden de Firebase Auth.

Colección `users`, con el uid de Firebase como id del documento:

    users/{uid}
      name       string
      email      string   (normalizado: minúsculas, sin espacios)
      role       string   ("SELLER" | "BUYER")
      created_at timestamp

Colección `listings`, con id generado por Firestore:

    listings/{id}
      seller_uid string
      photos     array<string>
      published  boolean
      created_at timestamp
"""
import hashlib
import json
import logging
from urllib.parse import quote
from uuid import uuid4

from firebase_admin import auth, firestore, storage

from .fields import normalize_account_email
from .firebase import get_app

logger = logging.getLogger(__name__)

USERS_COLLECTION = "users"
LISTINGS_COLLECTION = "listings"
DECISIONS_COLLECTION = "decisions"


def _users():
    return firestore.client(app=get_app()).collection(USERS_COLLECTION)


def _listings():
    return firestore.client(app=get_app()).collection(LISTINGS_COLLECTION)


def _public_profile(uid, data):
    # Solo los campos del contrato de la API; created_at y futuros campos no salen.
    return {"uid": uid, "name": data["name"], "email": data["email"], "role": data["role"]}


def create_user_profile(uid, *, name, email, role) -> dict:
    """Crea el perfil del usuario. Falla si ya existe un documento con ese uid.

    Las excepciones de Firestore se propagan: la vista decide la acción
    compensatoria (borrar el usuario de Firebase Auth recién creado).
    """
    profile = {"name": name, "email": normalize_account_email(email), "role": role}
    # create() en lugar de set(): nunca sobrescribe el perfil de otro usuario.
    _users().document(uid).create({**profile, "created_at": firestore.SERVER_TIMESTAMP})
    return _public_profile(uid, profile)


def get_user_profile(uid) -> dict | None:
    """Combina identidad Auth y rol Firestore; None si no existe el perfil."""
    snapshot = _users().document(uid).get()
    if not snapshot.exists:
        return None
    data = snapshot.to_dict()
    user = auth.get_user(uid, app=get_app())
    # Auth es la fuente de email y nombre vigente. Los perfiles anteriores
    # sin display_name conservan el nombre del documento hasta su primera edición.
    data["email"] = normalize_account_email(user.email)
    data["name"] = user.display_name or data["name"]
    return _public_profile(uid, data)


def _storage_bucket():
    return storage.bucket(app=get_app())


def create_listing(uid, *, values, photos) -> dict:
    """Sube fotografías y crea el anuncio, compensando fallos confirmados."""
    stored_values = {
        **values,
        "price_cents": int(values["price"] * 100),
        "surface_hundredths": int(values["surface"] * 100),
    }
    stored_values.pop("price")
    stored_values.pop("surface")
    bucket = _storage_bucket()
    uploaded = []
    reference = _listings().document()
    listing = {
        **stored_values,
        "seller_uid": uid,
        "photos": [],
        "published": True,
        "created_at": firestore.SERVER_TIMESTAMP,
    }
    for photo in photos:
        name = f"listings/{uid}/{uuid4().hex}"
        blob = bucket.blob(name)
        uploaded.append(blob)
        try:
            photo.seek(0)
            blob.upload_from_file(photo, content_type=photo.content_type)
            token = uuid4().hex
            blob.metadata = {"firebaseStorageDownloadTokens": token}
            blob.patch()
            bucket_name = bucket.name
            url = (
                f"https://firebasestorage.googleapis.com/v0/b/{bucket_name}/o/"
                f"{quote(name, safe='')}?alt=media&token={token}"
            )
            listing["photos"].append(url)
        except Exception:
            _cleanup_uploaded(uploaded)
            raise

    try:
        reference.create(listing)
    except Exception:
        try:
            snapshot = reference.get()
        except Exception as probe_error:
            logger.error(
                "No se pudo determinar si la publicación %s se guardó (%s); "
                "se conservan sus fotografías para conciliación.",
                reference.id,
                type(probe_error).__name__,
            )
            raise
        if snapshot.exists:
            logger.warning(
                "La publicación %s existe pese al error de confirmación; "
                "no se borran sus fotografías.",
                reference.id,
            )
            return {"id": reference.id}
        _cleanup_uploaded(uploaded)
        raise
    return {"id": reference.id}


def get_active_listings():
    """Devuelve los anuncios publicados con los valores en unidades de la API."""
    records = []
    query = _listings().where("published", "==", True).order_by("created_at")
    for snapshot in query.stream():
        data = snapshot.to_dict()
        if not data.get("published"):
            continue
        records.append({
            "id": snapshot.id,
            "seller_uid": data.get("seller_uid"),
            "title": data.get("title", ""),
            "street": data.get("street", ""),
            "city": data.get("city", ""),
            "postal_code": data.get("postal_code", ""),
            "description": data.get("description", ""),
            "price": data.get("price_cents", 0) / 100,
            "surface": data.get("surface_hundredths", 0) / 100,
            "bedrooms": data.get("bedrooms", 0),
            "bathrooms": data.get("bathrooms", 0),
            "people": data.get("people", 0),
            "shared_accommodation": bool(data.get("shared_accommodation", False)),
            "photos": list(data.get("photos", [])),
            "published": True,
        })
    return records


def get_explorable_listings(uid, *, limit=10, offset=0):
    """Returns active listings not previously decided by the buyer."""
    client = firestore.client(app=get_app())
    decided = {
        snapshot.id
        for snapshot in client.collection(DECISIONS_COLLECTION)
        .where("buyer_uid", "==", uid)
        .stream()
    }
    listings = [
        listing for listing in get_active_listings()
        if listing["id"] not in decided and listing.get("seller_uid") != uid
    ]
    page = listings[offset:offset + limit]
    next_offset = offset + limit if offset + limit < len(listings) else None
    return page, next_offset


def save_property_decision(uid, property_id, decision):
    """Persists a buyer decision and returns whether it created a match."""
    client = firestore.client(app=get_app())
    reference = client.collection(DECISIONS_COLLECTION).document(f"{uid}_{property_id}")
    existing = reference.get()
    if existing.exists:
        previous = existing.to_dict().get("decision")
        if previous == decision:
            return {"decision": decision, "match": False, "duplicate": True}
        raise ValueError("A different decision already exists.")
    listing = client.collection(LISTINGS_COLLECTION).document(property_id).get()
    if not listing.exists or not listing.to_dict().get("published"):
        raise LookupError("Property not found.")
    data = listing.to_dict()
    if data.get("seller_uid") == uid:
        raise PermissionError("A seller cannot decide on its own property.")
    reference.create({
        "buyer_uid": uid,
        "property_id": property_id,
        "decision": decision,
        "created_at": firestore.SERVER_TIMESTAMP,
    })
    return {"decision": decision, "match": False, "duplicate": False}


def _cleanup_uploaded(uploaded):
    for blob in uploaded:
        try:
            blob.delete()
        except Exception as cleanup_error:
            logger.error(
                "No se pudo limpiar una fotografía de la publicación (%s).",
                type(cleanup_error).__name__,
            )


def update_user_profile(uid, values):
    """Una sola escritura en Auth: nombre/email comparten la misma operación.

    Auth es la fuente vigente de campos editables; Firestore conserva únicamente
    el rol, relaciones y los datos históricos del registro. No hay dual write.
    """
    profile = get_user_profile(uid)
    if profile is None:
        return None
    if not values or set(values) - {"name", "email"}:
        raise ValueError("Campos no editables.")
    changes = {}
    if "name" in values:
        changes["display_name"] = values["name"]
    if "email" in values:
        changes["email"] = normalize_account_email(values["email"])
        if changes["email"] != profile["email"]:
            changes["email_verified"] = False
    updated = auth.update_user(uid, app=get_app(), **changes)
    return {
        "uid": uid, "name": updated.display_name or profile["name"],
        "email": normalize_account_email(updated.email), "role": profile["role"],
    }


def _revocation_document(uid, auth_time):
    # ID opaco, determinista y seguro aunque el uid contenga separadores.
    key = hashlib.sha256(json.dumps([uid, auth_time]).encode("utf-8")).hexdigest()
    return firestore.client(app=get_app()).collection("revoked_sessions").document(key)


def is_session_revoked(uid, auth_time):
    return _revocation_document(uid, auth_time).get().exists


def revoke_session(uid, auth_time):
    # set() hace la operación idempotente; no se almacena ningún token.
    # No caducar estos documentos: un refresh token conserva auth_time.
    _revocation_document(uid, auth_time).set({"revoked": True})


# Única colección de avisos; US4 podrá escribir aquí en una implementación futura.
NOTIFICATIONS_COLLECTION = "notifications"


def get_notifications(uid, *, limit, position=None):
    """Solo lectura, con filtro de destinatario y paginación en Firestore."""
    from google.cloud.firestore_v1.base_query import FieldFilter

    collection = firestore.client(app=get_app()).collection(NOTIFICATIONS_COLLECTION)
    query = (
        collection.where(filter=FieldFilter("recipient_uid", "==", uid))
        .order_by("created_at", direction=firestore.Query.DESCENDING)
        .order_by("__name__", direction=firestore.Query.DESCENDING)
    )
    if position is not None:
        created_at, identifier = position
        query = query.start_after({
            "created_at": created_at, "__name__": collection.document(identifier),
        })
    records = []
    for snapshot in query.limit(limit).stream():
        data = snapshot.to_dict()
        if data["recipient_uid"] != uid:
            raise ValueError("Destinatario inconsistente.")
        if not all(isinstance(data[field], str) for field in ("type", "message")):
            raise ValueError("Contenido de aviso inconsistente.")
        records.append({
            "id": snapshot.id, "type": data["type"],
            "message": data["message"], "created_at": data["created_at"],
        })
    return records
