"""Único módulo del proyecto que habla con Firestore y Firebase Storage.

Las vistas llaman aquí, nunca a Firestore directamente. Si algún día se cambia
de base de datos, se reescribe este fichero y nada más.

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
import logging
from urllib.parse import quote
from uuid import uuid4

from firebase_admin import firestore, storage

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
    """Devuelve el perfil del usuario, o None si no tiene documento en Firestore."""
    snapshot = _users().document(uid).get()
    if not snapshot.exists:
        return None
    return _public_profile(uid, snapshot.to_dict())


def _storage_bucket():
    return storage.bucket(app=get_app())


def create_listing(uid, *, values, photos) -> dict:
    """Sube fotografías y crea el anuncio, compensando cualquier fallo."""
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
    try:
        for photo in photos:
            name = f"listings/{uid}/{uuid4().hex}"
            blob = bucket.blob(name)
            photo.seek(0)
            blob.upload_from_file(photo, content_type=photo.content_type)
            uploaded.append(blob)
            token = uuid4().hex
            blob.metadata = {"firebaseStorageDownloadTokens": token}
            blob.patch()
            bucket_name = bucket.name
            url = (
                f"https://firebasestorage.googleapis.com/v0/b/{bucket_name}/o/"
                f"{quote(name, safe='')}?alt=media&token={token}"
            )
            listing["photos"].append(url)
        reference.create(listing)
    except Exception:
        for blob in uploaded:
            try:
                blob.delete()
            except Exception as cleanup_error:
                logger.error(
                    "No se pudo limpiar una fotografía de la publicación (%s).",
                    type(cleanup_error).__name__,
                )
        raise
    return {"id": reference.id, **listing, "price": str(values["price"]), "surface": str(values["surface"])}
