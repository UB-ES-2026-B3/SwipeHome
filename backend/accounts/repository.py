"""Único módulo del proyecto que habla con Firestore.

Las vistas llaman aquí, nunca a Firestore directamente. Si algún día se cambia
de base de datos, se reescribe este fichero y nada más.

Colección `users`, con el uid de Firebase como id del documento:

    users/{uid}
      name       string
      email      string   (normalizado: minúsculas, sin espacios)
      role       string   ("SELLER" | "BUYER")
      created_at timestamp
"""
from firebase_admin import firestore

from .fields import normalize_account_email
from .firebase import get_app

USERS_COLLECTION = "users"


def _users():
    return firestore.client(app=get_app()).collection(USERS_COLLECTION)


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
