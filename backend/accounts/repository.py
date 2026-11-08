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
        related = {}
        if "match_id" in data:
            fields = ("match_id", "buyer_uid", "buyer_name", "listing_id", "listing_title")
            if not all(isinstance(data.get(field), str) and data[field] for field in fields):
                raise ValueError("Relaciones de aviso inconsistentes.")
            related = {field: data[field] for field in fields}
        records.append({
            **related,
            "id": snapshot.id, "type": data["type"],
            "message": data["message"], "created_at": data["created_at"],
        })
    return records


SWIPES_COLLECTION = "swipes"
MATCHES_COLLECTION = "matches"


class ListingNotFound(Exception):
    pass


class DecisionConflict(Exception):
    pass


class InconsistentDecision(RuntimeError):
    """Datos fuera del contrato: nunca devolver éxito ni repararlos silenciosamente."""


def decision_key(buyer_uid, listing_id):
    # JSON evita ambigüedades de concatenación y admite UIDs con separadores.
    return hashlib.sha256(json.dumps([buyer_uid, listing_id], ensure_ascii=True).encode("utf-8")).hexdigest()


def record_decision(buyer_uid, listing_id, value, *, buyer_name):
    """Único escritor del conjunto. Todas las lecturas preceden a las escrituras.

    Firestore impone identidad única del documento y create exige inexistencia.
    El servicio impone LIKE/PASS y coherencia referencial; no son CHECK/FK SQL.
    El SDK reejecuta transacciones abortadas por contención. Una colisión create
    se reconsulta en una transacción NUEVA, nunca dentro de una fallida.
    """
    import random
    import time

    from google.api_core.exceptions import Aborted, AlreadyExists

    from .pagination import valid_document_id

    if value not in {"LIKE", "PASS"} or not valid_document_id(listing_id):
        raise ValueError("Decisión inválida.")
    client = firestore.client(app=get_app())
    key = decision_key(buyer_uid, listing_id)
    refs = {
        "listing": client.collection(LISTINGS_COLLECTION).document(listing_id),
        "decision": client.collection(SWIPES_COLLECTION).document(key),
        "match": client.collection(MATCHES_COLLECTION).document(key),
        "notice": client.collection(NOTIFICATIONS_COLLECTION).document("match-" + key),
    }
    for attempt in range(5):
        try:
            return _record_decision(client.transaction(max_attempts=10), refs, buyer_uid, listing_id, value, buyer_name)
        except (Aborted, AlreadyExists):
            if attempt == 4:
                raise
        except ValueError as error:
            # El SDK envuelve en ValueError los abortos agotados en commit.
            if not isinstance(error.__cause__, Aborted) or attempt == 4:
                raise
        # También puede abortar una LECTURA; el SDK solo reintenta el commit.
        # Nunca reutilizar la transacción abortada ni sobrescribir una decisión.
        time.sleep(random.uniform(0.02, min(0.5, 0.05 * (2 ** attempt))))


def _record_decision(transaction, refs, buyer_uid, listing_id, value, buyer_name):
    # El wrapper SDK conserva retry_id: crear uno por llamada, no compartir
    # su estado entre los hilos que atienden peticiones simultáneas.
    operation = firestore.transactional(_write_decision)
    return operation(transaction, refs, buyer_uid, listing_id, value, buyer_name)


def _write_decision(transaction, refs, buyer_uid, listing_id, value, buyer_name):
    from datetime import datetime, timezone

    from properties.serialization import published_listing

    snapshots = {name: ref.get(transaction=transaction) for name, ref in refs.items()}
    listing = snapshots["listing"].to_dict()
    if not snapshots["listing"].exists or not published_listing(listing):
        raise ListingNotFound()
    decision = snapshots["decision"].to_dict()
    match = snapshots["match"].to_dict()
    notice = snapshots["notice"].to_dict()
    key = refs["decision"].id
    if snapshots["decision"].exists:
        if decision.get("buyer_uid") != buyer_uid or decision.get("listing_id") != listing_id:
            raise InconsistentDecision()
        if decision.get("value") not in {"LIKE", "PASS"}:
            raise InconsistentDecision()
        if decision["value"] != value:
            raise DecisionConflict()
        if value == "LIKE":
            if (
                not snapshots["match"].exists or not snapshots["notice"].exists
                or match.get("buyer_uid") != buyer_uid or match.get("listing_id") != listing_id
                or match.get("decision_id") != key or notice.get("match_id") != refs["match"].id
                or notice.get("recipient_uid") != listing["seller_uid"]
                or notice.get("buyer_uid") != buyer_uid or notice.get("listing_id") != listing_id
            ):
                raise InconsistentDecision()
        elif snapshots["match"].exists or snapshots["notice"].exists:
            raise InconsistentDecision()
        return {"id": key, **decision}, None if match is None else {"id": key, **match}, False
    if snapshots["match"].exists or snapshots["notice"].exists:
        raise InconsistentDecision()
    created_at = datetime.now(timezone.utc)
    decision = {
        "buyer_uid": buyer_uid, "listing_id": listing_id,
        "value": value, "created_at": created_at,
    }
    transaction.create(refs["decision"], decision)
    match = None
    if value == "LIKE":
        match = {
            "buyer_uid": buyer_uid, "listing_id": listing_id,
            "decision_id": key, "created_at": created_at,
        }
        transaction.create(refs["match"], match)
        transaction.create(refs["notice"], {
            "recipient_uid": listing["seller_uid"], "match_id": key,
            "buyer_uid": buyer_uid, "buyer_name": buyer_name,
            "listing_id": listing_id, "listing_title": listing["title"],
            "type": "MATCH", "message": "Tienes un nuevo match.",
            "created_at": created_at,
        })
    return {"id": key, **decision}, None if match is None else {"id": key, **match}, True


def get_pending_listings(buyer_uid, *, limit, position=None):
    """Recorre lotes con cursor y carga decisiones en batch, sin OFFSET ni N+1.

    Se busca un pendiente adicional. El cursor público siempre sale del último
    resultado ENTREGADO, nunca del último documento inspeccionado.
    """
    from google.cloud.firestore_v1.base_query import FieldFilter

    from properties.serialization import listing_item, published_listing

    client = firestore.client(app=get_app())
    collection = client.collection(LISTINGS_COLLECTION)
    query = (
        collection.where(filter=FieldFilter("published", "==", True))
        .order_by("created_at", direction=firestore.Query.DESCENDING)
        .order_by("__name__", direction=firestore.Query.DESCENDING)
    )
    records = []
    batch_size = max(20, limit)
    while len(records) < limit:
        bounded = query
        if position is not None:
            bounded = bounded.start_after({
                "created_at": position[0], "__name__": collection.document(position[1]),
            })
        snapshots = list(bounded.limit(batch_size).stream())
        if not snapshots:
            break
        decisions = {
            snapshot.id for snapshot in client.get_all([
                client.collection(SWIPES_COLLECTION).document(decision_key(buyer_uid, row.id))
                for row in snapshots
            ]) if snapshot.exists
        }
        for snapshot in snapshots:
            data = snapshot.to_dict()
            if decision_key(buyer_uid, snapshot.id) not in decisions and published_listing(data):
                records.append(listing_item(snapshot.id, data))
                if len(records) == limit:
                    break
        if len(snapshots) < batch_size:
            break
        last = snapshots[-1]
        position = (last.to_dict()["created_at"], last.id)
    return records
