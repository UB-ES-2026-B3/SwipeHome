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
