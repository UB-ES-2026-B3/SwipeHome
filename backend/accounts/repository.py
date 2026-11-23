"""Único módulo del proyecto que habla con Firestore y Azure Blob Storage.

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
from uuid import uuid4

from azure.storage.blob import ContentSettings
from firebase_admin import auth, firestore

from .azure_storage import get_container_client
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


def create_listing(uid, *, values, photos) -> dict:
    """Sube fotografías y crea el anuncio, compensando fallos confirmados."""
    stored_values = {
        **values,
        "price_cents": int(values["price"] * 100),
        "surface_hundredths": int(values["surface"] * 100),
    }
    stored_values.pop("price")
    stored_values.pop("surface")
    container = get_container_client()
    uploaded = []
    reference = _listings().document()
    listing = {
        **stored_values,
        "seller_uid": uid,
        "photos": [],
        "published": True,
        "availability": "ACTIVE",
        "closure_reason": None,
        "version": 1,
        "created_at": firestore.SERVER_TIMESTAMP,
        "updated_at": firestore.SERVER_TIMESTAMP,
    }
    for photo in photos:
        # El contenedor ya separa las fotos de anuncios: sin prefijo adicional.
        name = f"{uid}/{uuid4().hex}"
        blob = container.get_blob_client(name)
        uploaded.append(blob)
        try:
            photo.seek(0)
            # overwrite=True: si se pierde la respuesta de un intento que sí
            # llegó, el reintento del SDK no falla con 409. El nombre es un
            # uuid4, así que nunca pisa la foto de otro anuncio.
            blob.upload_blob(
                photo,
                length=photo.size,
                overwrite=True,
                content_settings=ContentSettings(content_type=photo.content_type),
            )
            # El contenedor tiene acceso anónimo «Blob»: la URL pública basta,
            # sin token de descarga ni SAS.
            listing["photos"].append(blob.url)
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
        if not data.get("published") or listing_availability(data) != "ACTIVE":
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
            "availability": listing_availability(data),
            "closure_reason": data.get("closure_reason"),
            "version": int(data.get("version", 1)),
        })
    return records


def get_seller_listings(uid):
    """Devuelve los anuncios publicados por un vendedor concreto."""
    records = []
    for snapshot in _listings().stream():
        data = snapshot.to_dict()
        if data.get("published") is not True or data.get("seller_uid") != uid:
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
            "availability": listing_availability(data),
            "closure_reason": data.get("closure_reason"),
            "version": int(data.get("version", 1)),
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
    """Persists a buyer decision using canonical record_decision."""
    profile = get_user_profile(uid)
    if profile and profile.get("role") != "BUYER":
        raise PermissionError("Solo un comprador puede registrar decisiones.")
    buyer_name = profile.get("name", "") if profile else ""
    decision_record, match_record, created = record_decision(
        uid, property_id, decision, buyer_name=buyer_name
    )
    return {
        "decision": decision,
        "match": bool(match_record),
        "duplicate": not created,
    }


def _cleanup_uploaded(uploaded):
    for blob in uploaded:
        try:
            blob.delete_blob()
        except Exception as cleanup_error:
            logger.error(
                "No se pudo limpiar una fotografía de la publicación (%s).",
                type(cleanup_error).__name__,
            )
            _queue_photo_cleanup(getattr(blob, "url", None))


def _cleanup_removed_blob(photo_url):
    try:
        container = get_container_client()
        container_prefix = f"/{container.container_name}/"
        if container_prefix in photo_url:
            blob_name = photo_url.split(container_prefix, 1)[1].split("?")[0]
        else:
            parts = photo_url.split("?")[0].rstrip("/").split("/")
            if len(parts) >= 2:
                blob_name = f"{parts[-2]}/{parts[-1]}"
            else:
                blob_name = parts[-1]
        blob = container.get_blob_client(blob_name)
        blob.delete_blob()
    except Exception as cleanup_error:
        logger.warning(
            "No se pudo limpiar una fotografía retirada de la publicación %s (%s).",
            photo_url,
            type(cleanup_error).__name__,
        )
        _queue_photo_cleanup(photo_url)


def _queue_photo_cleanup(photo_url):
    if not photo_url:
        return
    try:
        client = _selection_client()
        key = decision_key(photo_url, "photo-cleanup")
        client.collection(PHOTO_CLEANUP_COLLECTION).document(key).set({
            "photo_url": photo_url,
            "processed": False,
            "attempts": 0,
            "created_at": firestore.SERVER_TIMESTAMP,
            "updated_at": firestore.SERVER_TIMESTAMP,
        }, merge=True)
    except Exception as queue_error:
        logger.error(
            "No se pudo registrar la fotografía huérfana para recuperación (%s).",
            type(queue_error).__name__,
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
        if "listing_id" in data and "match_id" not in data:
            related = {"listing_id": data["listing_id"], "listing_title": data.get("listing_title", "")}
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


class MatchNotFound(Exception):
    pass


class DecisionConflict(Exception):
    pass


class VersionConflict(DecisionConflict):
    pass


class InvalidPhotos(ValueError):
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
            needs_update = {}
            if "status" not in match:
                needs_update["status"] = "PENDING"
            if "seller_uid" not in match:
                needs_update["seller_uid"] = listing["seller_uid"]
            if "buyer_name" not in match and buyer_name:
                needs_update["buyer_name"] = buyer_name
            if "listing_title" not in match and listing.get("title"):
                needs_update["listing_title"] = listing["title"]
            if needs_update:
                transaction.update(refs["match"], needs_update)
                match = {**match, **needs_update}
        elif snapshots["match"].exists or snapshots["notice"].exists:
            raise InconsistentDecision()
        return {"id": key, **decision}, None if match is None else {"id": key, "status": match.get("status", "PENDING"), **match}, False
    if snapshots["match"].exists or snapshots["notice"].exists:
        raise InconsistentDecision()
    if listing_availability(listing) != "ACTIVE":
        raise DecisionConflict()
    created_at = datetime.now(timezone.utc)
    decision = {
        "buyer_uid": buyer_uid, "listing_id": listing_id,
        "value": value, "created_at": created_at,
    }
    transaction.create(refs["decision"], decision)
    match = None
    if value == "LIKE":
        match = {
            "buyer_uid": buyer_uid,
            "buyer_name": buyer_name,
            "seller_uid": listing["seller_uid"],
            "listing_id": listing_id,
            "listing_title": listing["title"],
            "decision_id": key,
            "status": "PENDING",
            "created_at": created_at,
        }
        transaction.create(refs["match"], match)
        transaction.create(refs["notice"], {
            "recipient_uid": listing["seller_uid"], "match_id": key,
            "buyer_uid": buyer_uid, "buyer_name": buyer_name,
            "listing_id": listing_id, "listing_title": listing["title"],
            "type": "INTEREST", "message": "Tienes un nuevo candidato interesado en tu vivienda.",
            "created_at": created_at,
        })
    return {"id": key, **decision}, None if match is None else {"id": key, **match}, True


def get_pending_listings(buyer_uid, *, limit, position=None, preferences=None):
    """Recorre lotes con cursor y carga decisiones en batch, sin OFFSET ni N+1.

    Se busca un pendiente adicional. El cursor público siempre sale del último
    resultado ENTREGADO, nunca del último documento inspeccionado.
    """
    from google.cloud.firestore_v1.base_query import FieldFilter

    from properties.serialization import listing_item, published_listing
    from properties.preferences import matches_preferences

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
        eligible = [
            (row, data) for row in snapshots
            if published_listing(data := row.to_dict())
            and listing_availability(data) == "ACTIVE"
            and (preferences is None or matches_preferences(data, preferences))
        ]
        decisions = {
            snapshot.id for snapshot in client.get_all([
                client.collection(SWIPES_COLLECTION).document(decision_key(buyer_uid, row.id))
                for row, _ in eligible
            ]) if snapshot.exists
        } if eligible else set()
        for snapshot, data in eligible:
            if decision_key(buyer_uid, snapshot.id) not in decisions:
                records.append(listing_item(snapshot.id, data))
                if len(records) == limit:
                    break
        if len(snapshots) < batch_size:
            break
        last = snapshots[-1]
        position = (last.to_dict()["created_at"], last.id)
    return records


def get_listing(listing_id):
    client = firestore.client(app=get_app())
    snapshot = client.collection(LISTINGS_COLLECTION).document(listing_id).get()
    if not snapshot.exists:
        return None
    return {"id": snapshot.id, **snapshot.to_dict()}


def record_seller_decision(seller_uid, match_id, value):
    """Decisión del Vendedor sobre una candidatura PENDING.

    LIKE transforma PENDING en CONFIRMED (guarda confirmed_at y decided_at).
    PASS transforma PENDING en REJECTED (guarda decided_at).
    Idempotente ante la misma decisión (devuelve 200).
    Rechaza decisiones contradictorias con 409 DecisionConflict.
    """
    import random
    import time

    from google.api_core.exceptions import Aborted, AlreadyExists

    from .pagination import valid_document_id

    if value not in {"LIKE", "PASS"} or not valid_document_id(match_id):
        raise ValueError("Decisión inválida.")
    client = firestore.client(app=get_app())
    match_ref = client.collection(MATCHES_COLLECTION).document(match_id)
    for attempt in range(5):
        try:
            return _record_seller_decision(client.transaction(max_attempts=10), match_ref, seller_uid, match_id, value)
        except (Aborted, AlreadyExists):
            if attempt == 4:
                raise
        except ValueError as error:
            if not isinstance(error.__cause__, Aborted) or attempt == 4:
                raise
        time.sleep(random.uniform(0.02, min(0.5, 0.05 * (2 ** attempt))))


def _record_seller_decision(transaction, match_ref, seller_uid, match_id, value):
    operation = firestore.transactional(_write_seller_decision)
    return operation(transaction, match_ref, seller_uid, match_id, value)


def _write_seller_decision(transaction, match_ref, seller_uid, match_id, value):
    from datetime import datetime, timezone

    match_snap = match_ref.get(transaction=transaction)
    if not match_snap.exists:
        raise MatchNotFound()
    match_data = match_snap.to_dict()

    # H4: verify actual property owner dynamically from listings collection
    client = firestore.client(app=get_app())
    listing_snap = client.collection(LISTINGS_COLLECTION).document(match_data["listing_id"]).get(transaction=transaction)
    if not listing_snap.exists:
        raise MatchNotFound()
    listing_data = listing_snap.to_dict()
    if listing_data.get("seller_uid") != seller_uid:
        raise MatchNotFound()

    # H3: verify swipe origin coherence
    expected_key = decision_key(match_data.get("buyer_uid"), match_data.get("listing_id"))
    decision_id = match_data.get("decision_id", match_id)
    if match_id != expected_key or decision_id != expected_key:
        raise InconsistentDecision()

    swipe_snap = client.collection(SWIPES_COLLECTION).document(decision_id).get(transaction=transaction)
    if not swipe_snap.exists:
        raise InconsistentDecision()
    swipe_data = swipe_snap.to_dict()
    if (
        swipe_data.get("value") != "LIKE"
        or swipe_data.get("buyer_uid") != match_data.get("buyer_uid")
        or swipe_data.get("listing_id") != match_data.get("listing_id")
    ):
        raise InconsistentDecision()

    current_status = match_data.get("status", "PENDING")
    if current_status == "PENDING":
        if listing_availability(listing_data) == "CLOSED":
            raise DecisionConflict()
        now = datetime.now(timezone.utc)
        if value == "LIKE":
            new_status = "CONFIRMED"
            updates = {
                "status": "CONFIRMED",
                "seller_uid": seller_uid,
                "confirmed_at": now,
                "decided_at": now,
            }
        else:
            new_status = "REJECTED"
            updates = {
                "status": "REJECTED",
                "seller_uid": seller_uid,
                "decided_at": now,
            }
        if "buyer_name" not in match_data and match_data.get("buyer_uid"):
            u_snap = client.collection(USERS_COLLECTION).document(match_data["buyer_uid"]).get(transaction=transaction)
            if u_snap.exists:
                updates["buyer_name"] = u_snap.to_dict().get("name", "")
        if "listing_title" not in match_data and listing_data.get("title"):
            updates["listing_title"] = listing_data["title"]

        transaction.update(match_ref, updates)
        return {
            "id": match_id,
            "status": new_status,
            "created_at": match_data.get("created_at"),
            "decided_at": updates["decided_at"],
            **({"confirmed_at": updates["confirmed_at"]} if new_status == "CONFIRMED" else {}),
        }, True
    elif current_status == "CONFIRMED":
        if value == "LIKE":
            return {
                "id": match_id,
                "status": "CONFIRMED",
                "created_at": match_data.get("created_at"),
                "decided_at": match_data.get("decided_at", match_data.get("confirmed_at")),
                "confirmed_at": match_data.get("confirmed_at"),
            }, False
        else:
            raise DecisionConflict()
    elif current_status == "REJECTED":
        if value == "PASS":
            return {
                "id": match_id,
                "status": "REJECTED",
                "created_at": match_data.get("created_at"),
                "decided_at": match_data.get("decided_at"),
            }, False
        else:
            raise DecisionConflict()
    else:
        raise InconsistentDecision()


def _seller_match_listings(client, seller_uid, listing_id):
    from google.cloud.firestore_v1.base_query import FieldFilter

    collection = client.collection(LISTINGS_COLLECTION)
    query = collection.where(filter=FieldFilter("seller_uid", "==", seller_uid))
    if listing_id:
        query = query.where(filter=FieldFilter("__name__", "==", collection.document(listing_id)))
    return {snapshot.id: snapshot.to_dict() for snapshot in query.stream()}


def get_candidates(seller_uid, *, limit, position=None, listing_id=None):
    """Consulta paginada de candidatos PENDING de viviendas del Vendedor."""
    from google.cloud.firestore_v1.base_query import FieldFilter

    client = firestore.client(app=get_app())
    seller_listings = _seller_match_listings(client, seller_uid, listing_id)

    # Backfill legacy matches or sync updated ownership for seller's listings (H1 and H4)
    for lid, ldata in seller_listings.items():
        for m in client.collection(MATCHES_COLLECTION).where("listing_id", "==", lid).stream():
            m_dict = m.to_dict()
            sync_updates = {}
            if m_dict.get("status") is None:
                sync_updates["status"] = "PENDING"
            if m_dict.get("seller_uid") != seller_uid and m_dict.get("status", "PENDING") == "PENDING":
                sync_updates["seller_uid"] = seller_uid
            if not m_dict.get("listing_title") and ldata.get("title"):
                sync_updates["listing_title"] = ldata["title"]
            if not m_dict.get("buyer_name") and m_dict.get("buyer_uid"):
                u_snap = client.collection(USERS_COLLECTION).document(m_dict["buyer_uid"]).get()
                if u_snap.exists:
                    sync_updates["buyer_name"] = u_snap.to_dict().get("name", "")
            if sync_updates:
                m.reference.update(sync_updates)

    collection = client.collection(MATCHES_COLLECTION)
    query = (
        collection.where(filter=FieldFilter("seller_uid", "==", seller_uid))
        .where(filter=FieldFilter("status", "==", "PENDING"))
    )
    if listing_id:
        query = query.where(filter=FieldFilter("listing_id", "==", listing_id))
    query = query.order_by("created_at", direction=firestore.Query.DESCENDING)
    query = query.order_by("__name__", direction=firestore.Query.DESCENDING)
    if position is not None:
        created_at, identifier = position
        query = query.start_after({
            "created_at": created_at, "__name__": collection.document(identifier),
        })
    records = []
    for snapshot in query.limit(limit).stream():
        data = snapshot.to_dict()
        if data.get("listing_id") not in seller_listings:
            continue
        records.append({
            "id": snapshot.id,
            "status": "PENDING",
            "created_at": data["created_at"],
            "buyer_uid": data["buyer_uid"],
            "buyer_name": data.get("buyer_name", ""),
            "listing_id": data["listing_id"],
            "listing_title": data.get("listing_title", ""),
        })
    return records


def get_confirmed_matches(uid, role, *, limit, position=None, listing_id=None):
    """Consulta paginada de matches CONFIRMED para BUYER o SELLER."""
    from google.cloud.firestore_v1.base_query import FieldFilter

    client = firestore.client(app=get_app())
    seller_listings = None
    if role == "SELLER":
        seller_listings = _seller_match_listings(client, uid, listing_id)

    collection = client.collection(MATCHES_COLLECTION)
    filter_field = "buyer_uid" if role == "BUYER" else "seller_uid"
    query = (
        collection.where(filter=FieldFilter(filter_field, "==", uid))
        .where(filter=FieldFilter("status", "==", "CONFIRMED"))
    )
    if listing_id:
        query = query.where(filter=FieldFilter("listing_id", "==", listing_id))
    query = query.order_by("confirmed_at", direction=firestore.Query.DESCENDING)
    query = query.order_by("__name__", direction=firestore.Query.DESCENDING)
    if position is not None:
        confirmed_at, identifier = position
        query = query.start_after({
            "confirmed_at": confirmed_at, "__name__": collection.document(identifier),
        })
    records = []
    for snapshot in query.limit(limit).stream():
        data = snapshot.to_dict()
        if role == "SELLER" and seller_listings is not None and data.get("listing_id") not in seller_listings:
            continue
        records.append({
            "id": snapshot.id,
            "status": "CONFIRMED",
            "created_at": data.get("created_at"),
            "confirmed_at": data["confirmed_at"],
            "availability": listing_availability(seller_listings[data["listing_id"]]) if seller_listings is not None else None,
            "closure_reason": listing_closure_reason(seller_listings[data["listing_id"]]) if seller_listings is not None else None,
            "buyer_uid": data["buyer_uid"],
            "buyer_name": data.get("buyer_name", ""),
            "seller_uid": data.get("seller_uid", ""),
            "listing_id": data["listing_id"],
            "listing_title": data.get("listing_title", ""),
        })
    return records


PREFERENCES_COLLECTION = "search_preferences"


def get_search_preferences(uid):
    from properties.preferences import validate_preferences
    snap = firestore.client(app=get_app()).collection(PREFERENCES_COLLECTION).document(uid).get()
    values, errors = validate_preferences(snap.to_dict() if snap.exists else {})
    if errors:
        raise ValueError("Preferencias persistidas inválidas.")
    return values


def save_search_preferences(uid, values):
    # Una sola escritura atómica de sustitución. Nunca borrar antes de guardar.
    firestore.client(app=get_app()).collection(PREFERENCES_COLLECTION).document(uid).set(values)
    return dict(values)


def delete_search_preferences(uid):
    client = firestore.client(app=get_app())
    batch = client.batch()
    batch.delete(client.collection(PREFERENCES_COLLECTION).document(uid))
    batch.commit()


def get_filter_cities():
    from google.cloud.firestore_v1.base_query import FieldFilter
    from properties.serialization import published_listing
    query = _listings().where(filter=FieldFilter("published", "==", True))
    cities = {}
    for snap in query.stream():
        data = snap.to_dict()
        if published_listing(data) and listing_availability(data) == "ACTIVE":
            city = data["city"].strip()
            normalized = " ".join(city.split()).casefold()
            if normalized:
                cities.setdefault(normalized, city)
    return sorted(cities.values(), key=str.casefold)


# US9: documentos privados de coordinación e idempotencia, nunca serializados.
PROPOSALS_COLLECTION = "selection_proposals"
SELECTIONS_COLLECTION = "listing_selections"
PROPOSAL_REQUESTS_COLLECTION = "selection_requests"
SELECTION_EVENTS_COLLECTION = "selection_notification_events"
INLINE_CLOSURE_NOTICE_LIMIT = 100
CLOSURE_EVENT_BATCH_SIZE = 100
PHOTO_CLEANUP_COLLECTION = "photo_cleanup"


class ProposalNotFound(Exception):
    pass


def listing_availability(data):
    return data.get("availability", "ACTIVE" if data.get("published") else "PAUSED")


def listing_closure_reason(data):
    if listing_availability(data) != "CLOSED":
        return None
    raw = data.get("closure_reason")
    if raw in ("RENTED", "Alquiler acordado"):
        return "RENTED"
    return raw or "WITHDRAWN"


def _selection_client():
    return firestore.client(app=get_app())


def _selection_ref(client, listing_id):
    return client.collection(SELECTIONS_COLLECTION).document(listing_id)


def _owned_listing(transaction, client, listing_id, seller_uid):
    ref = client.collection(LISTINGS_COLLECTION).document(listing_id)
    snap = ref.get(transaction=transaction)
    if not snap.exists or snap.to_dict().get("seller_uid") != seller_uid:
        raise ProposalNotFound()
    return ref, snap.to_dict()


def _proposal_access(transaction, client, proposal_id, uid, role):
    ref = client.collection(PROPOSALS_COLLECTION).document(proposal_id)
    snap = ref.get(transaction=transaction)
    if not snap.exists:
        raise ProposalNotFound()
    data = snap.to_dict()
    if data.get("seller_uid" if role == "SELLER" else "buyer_uid") != uid:
        raise ProposalNotFound()
    listing_ref, listing = _owned_listing(transaction, client, data["listing_id"], data["seller_uid"])
    return ref, data, listing_ref, listing


def _proposal_notice(transaction, client, event, kind, recipient, listing_id, title, message=None):
    # No buyer, match ni propuesta en avisos de cierre a otros candidatos.
    key = decision_key(recipient, event + ":" + kind)
    messages = {
        "PROPOSAL": "Has recibido una propuesta de selección para una vivienda.",
        "ACCEPTED": "El comprador ha aceptado tu propuesta de selección.",
        "REJECTED": "El comprador ha rechazado tu propuesta de selección.",
        "CANCELLED": "El propietario ha cancelado tu propuesta de selección.",
        "LISTING_CLOSED": message or "La vivienda ya no está disponible: Alquiler acordado.",
    }
    transaction.create(client.collection(NOTIFICATIONS_COLLECTION).document("selection-" + key), {
        "recipient_uid": recipient, "type": kind, "message": message or messages.get(kind, ""),
        "listing_id": listing_id, "listing_title": title,
        "created_at": firestore.SERVER_TIMESTAMP,
    })


def create_proposal(seller_uid, listing_id, match_id, request_id):
    client = _selection_client()
    key = decision_key(seller_uid, request_id)
    proposal_ref = client.collection(PROPOSALS_COLLECTION).document(key)
    request_ref = client.collection(PROPOSAL_REQUESTS_COLLECTION).document(key)

    def write(tx):
        _, listing = _owned_listing(tx, client, listing_id, seller_uid)
        match_snap = client.collection(MATCHES_COLLECTION).document(match_id).get(transaction=tx)
        if not match_snap.exists:
            raise ProposalNotFound()
        match = match_snap.to_dict()
        if match.get("listing_id") != listing_id or match.get("seller_uid") != seller_uid:
            raise ProposalNotFound()
        previous = request_ref.get(transaction=tx)
        control_ref = _selection_ref(client, listing_id)
        control = control_ref.get(transaction=tx).to_dict() or {}
        if previous.exists:
            if previous.to_dict() != {"seller_uid": seller_uid, "listing_id": listing_id, "match_id": match_id, "request_id": request_id}:
                raise DecisionConflict()
            existing = proposal_ref.get(transaction=tx)
            if not existing.exists:
                raise InconsistentDecision()
            return False
        if match.get("status") != "CONFIRMED":
            raise DecisionConflict()
        buyer = client.collection(USERS_COLLECTION).document(match["buyer_uid"]).get(transaction=tx)
        if not buyer.exists or buyer.to_dict().get("role") != "BUYER":
            raise ProposalNotFound()
        if listing_availability(listing) not in {"ACTIVE", "PAUSED"} or control.get("pending_proposal_id") or control.get("accepted_proposal_id"):
            raise DecisionConflict()
        tx.create(proposal_ref, {
            "seller_uid": seller_uid, "buyer_uid": match["buyer_uid"], "listing_id": listing_id,
            "match_id": match_id, "request_id": request_id, "status": "PENDING",
            "created_at": firestore.SERVER_TIMESTAMP, "resolved_at": None, "resolved_by": None,
        })
        tx.create(request_ref, {"seller_uid": seller_uid, "listing_id": listing_id, "match_id": match_id, "request_id": request_id})
        tx.set(control_ref, {"pending_proposal_id": key}, merge=True)
        _proposal_notice(tx, client, key, "PROPOSAL", match["buyer_uid"], listing_id, listing["title"])
        return True

    created = _run_selection_transaction(client, write)
    return {"id": key, **proposal_ref.get().to_dict()}, created


def _run_selection_transaction(client, callback):
    import random
    import time
    from google.api_core.exceptions import Aborted, AlreadyExists
    for attempt in range(5):
        try:
            return firestore.transactional(callback)(client.transaction(max_attempts=10))
        except (Aborted, AlreadyExists):
            if attempt == 4:
                raise
        except ValueError as error:
            if not isinstance(error.__cause__, Aborted) or attempt == 4:
                raise
        time.sleep(random.uniform(0.02, 0.15))


def resolve_proposal(uid, role, proposal_id, status):
    from google.cloud.firestore_v1.base_query import FieldFilter
    if (role, status) not in {("BUYER", "ACCEPTED"), ("BUYER", "REJECTED"), ("SELLER", "CANCELLED")}:
        raise PermissionError()
    client = _selection_client()

    def write(tx):
        ref, data, listing_ref, listing = _proposal_access(tx, client, proposal_id, uid, role)
        control_ref = _selection_ref(client, data["listing_id"])
        control = control_ref.get(transaction=tx).to_dict() or {}
        if data["status"] == status and data["resolved_by"] == uid:
            return
        if data["status"] != "PENDING" or control.get("pending_proposal_id") != proposal_id or control.get("accepted_proposal_id"):
            raise DecisionConflict()
        match = client.collection(MATCHES_COLLECTION).document(data["match_id"]).get(transaction=tx).to_dict()
        if not match or match.get("status") != "CONFIRMED" or match.get("listing_id") != data["listing_id"] or match.get("buyer_uid") != data["buyer_uid"] or match.get("seller_uid") != data["seller_uid"]:
            raise DecisionConflict()
        if listing_availability(listing) not in {"ACTIVE", "PAUSED"}:
            raise DecisionConflict()
        recipients = set()
        if status == "ACCEPTED":
            # Lecturas antes de escrituras. Los escritores de matches también leen
            # listing: el cierre serializa la pertenencia al conjunto de avisos.
            query = client.collection(MATCHES_COLLECTION).where(filter=FieldFilter("listing_id", "==", data["listing_id"]))
            recipients = {m["buyer_uid"] for snap in query.stream(transaction=tx)
                          if (m := snap.to_dict()).get("status", "PENDING") in {"PENDING", "CONFIRMED"}}
            recipients.discard(data["buyer_uid"])
        tx.update(ref, {"status": status, "resolved_at": firestore.SERVER_TIMESTAMP, "resolved_by": uid})
        updates = {"pending_proposal_id": None}
        if status == "ACCEPTED":
            updates.update(accepted_proposal_id=proposal_id, selected_buyer_uid=data["buyer_uid"], selected_match_id=data["match_id"])
            tx.update(listing_ref, {
                "availability": "CLOSED",
                "closure_reason": "RENTED",
                "closed_at": firestore.SERVER_TIMESTAMP,
                "version": int(listing.get("version", 1)) + 1,
                "updated_at": firestore.SERVER_TIMESTAMP,
            })
        tx.set(control_ref, updates, merge=True)
        recipient = data["buyer_uid"] if status == "CANCELLED" else data["seller_uid"]
        _proposal_notice(tx, client, proposal_id, status, recipient, data["listing_id"], listing["title"])
        _closure_notices(tx, client, data["listing_id"], listing["title"], recipients)

    _run_selection_transaction(client, write)
    result = {"id": proposal_id, **client.collection(PROPOSALS_COLLECTION).document(proposal_id).get().to_dict()}
    if status == "ACCEPTED":
        try:
            process_selection_notifications(limit=10, listing_id=result["listing_id"])
        except Exception as error:
            # El cierre ya está confirmado y el evento duradero permite recuperar
            # las entregas restantes sin repetir las completadas.
            logger.error("Pendientes avisos duraderos de selección (%s).", type(error).__name__)
    return result


def get_proposal(uid, role, proposal_id):
    client = _selection_client()
    def read(tx):
        _, data, _, listing = _proposal_access(tx, client, proposal_id, uid, role)
        return {"id": proposal_id, **data}, listing
    return _run_selection_transaction(client, read)


def get_proposals(uid, role, *, limit, position=None):
    from google.cloud.firestore_v1.base_query import FieldFilter
    client = _selection_client()
    collection = client.collection(PROPOSALS_COLLECTION)
    query = collection.where(filter=FieldFilter("seller_uid" if role == "SELLER" else "buyer_uid", "==", uid))
    query = query.order_by("created_at", direction=firestore.Query.DESCENDING).order_by("__name__", direction=firestore.Query.DESCENDING)
    if position:
        query = query.start_after({"created_at": position[0], "__name__": collection.document(position[1])})
    records = []
    for snap in query.stream():
        try:
            data, _ = get_proposal(uid, role, snap.id)
        except ProposalNotFound:
            continue
        records.append(data)
        if len(records) == limit:
            break
    return records


def update_listing(seller_uid, listing_id, changes):
    client = _selection_client()
    def write(tx):
        ref, listing = _owned_listing(tx, client, listing_id, seller_uid)
        control = _selection_ref(client, listing_id).get(transaction=tx).to_dict() or {}
        if control.get("pending_proposal_id") or control.get("accepted_proposal_id") or listing_availability(listing) == "CLOSED":
            raise DecisionConflict()
        current_version = int(listing.get("version", 1))
        update_data = {
            **changes,
            "version": current_version + 1,
            "updated_at": firestore.SERVER_TIMESTAMP,
        }
        tx.update(ref, update_data)
    _run_selection_transaction(client, write)
    return get_listing(listing_id)



def _closure_notices(transaction, client, listing_id, title, recipients, closure_reason=None):
    recipients = sorted(recipients)
    event_suffix = ":withdrawn" if closure_reason == "WITHDRAWN" else ""
    msg = "La vivienda ya no está disponible: Retirada por el propietario." if closure_reason == "WITHDRAWN" else "La vivienda ya no está disponible: Alquiler acordado."
    if len(recipients) <= INLINE_CLOSURE_NOTICE_LIMIT:
        for recipient in recipients:
            _proposal_notice(transaction, client, listing_id + event_suffix, "LISTING_CLOSED", recipient, listing_id, title, msg)
        return
    # Congela los destinatarios elegibles al cierre en documentos acotados.
    # Ni el evento ni su ID incluyen el comprador elegido.
    for offset in range(0, len(recipients), CLOSURE_EVENT_BATCH_SIZE):
        key = decision_key(listing_id, "closure-batch-" + ("withdrawn-" if closure_reason == "WITHDRAWN" else "") + str(offset))
        transaction.create(client.collection(SELECTION_EVENTS_COLLECTION).document(key), {
            "listing_id": listing_id, "listing_title": title,
            "recipients": recipients[offset:offset + CLOSURE_EVENT_BATCH_SIZE],
            "processed": False, "created_at": firestore.SERVER_TIMESTAMP,
            "closure_reason": closure_reason,
        })


def process_selection_notifications(*, limit=100, listing_id=None):
    """Reejecutable por la API o el comando de recuperación; cada lote es atómico."""
    from google.cloud.firestore_v1.base_query import FieldFilter
    client = _selection_client()
    query = client.collection(SELECTION_EVENTS_COLLECTION).where(filter=FieldFilter("processed", "==", False))
    if listing_id is not None:
        query = query.where(filter=FieldFilter("listing_id", "==", listing_id))
    processed = 0
    for snapshot in query.limit(limit).stream():
        def deliver(tx):
            current = snapshot.reference.get(transaction=tx)
            if not current.exists or current.to_dict().get("processed"):
                return False
            event = current.to_dict()
            closure_reason = event.get("closure_reason")
            event_suffix = ":withdrawn" if closure_reason == "WITHDRAWN" else ""
            msg = "La vivienda ya no está disponible: Retirada por el propietario." if closure_reason == "WITHDRAWN" else "La vivienda ya no está disponible: Alquiler acordado."
            for recipient in event["recipients"]:
                _proposal_notice(tx, client, event["listing_id"] + event_suffix, "LISTING_CLOSED", recipient,
                                 event["listing_id"], event["listing_title"], message=msg)
            tx.update(snapshot.reference, {"processed": True, "processed_at": firestore.SERVER_TIMESTAMP})
            return True
        processed += int(_run_selection_transaction(client, deliver))
    return processed


def serialize_management_listing(listing_id, data, has_pending_proposal=False):
    from decimal import Decimal
    from properties.serialization import TEXT_FIELDS
    from .pagination import timestamp
    availability = listing_availability(data)
    closure_reason = listing_closure_reason(data)

    can_edit = availability in ("ACTIVE", "PAUSED") and not has_pending_proposal
    can_pause = availability == "ACTIVE" and not has_pending_proposal
    can_reactivate = availability == "PAUSED" and not has_pending_proposal
    can_withdraw = availability in ("ACTIVE", "PAUSED") and not has_pending_proposal

    actions = []
    if can_edit:
        actions.append("edit")
    if can_pause:
        actions.append("pause")
    if can_reactivate:
        actions.append("reactivate")
    if can_withdraw:
        actions.append("withdraw")

    price_str = str((Decimal(data["price_cents"]) / 100).quantize(Decimal("0.00"))) if "price_cents" in data else "0.00"
    surface_str = str((Decimal(data["surface_hundredths"]) / 100).quantize(Decimal("0.00"))) if "surface_hundredths" in data else "0.00"

    return {
        "id": listing_id,
        **{f: data.get(f, "") for f in TEXT_FIELDS},
        "price": price_str,
        "surface": surface_str,
        "price_val": data.get("price_cents", 0) / 100,
        "surface_val": data.get("surface_hundredths", 0) / 100,
        "bedrooms": data.get("bedrooms", 0),
        "bathrooms": data.get("bathrooms", 0),
        "people": data.get("people", 0),
        "shared_accommodation": bool(data.get("shared_accommodation", False)),
        "photos": list(data.get("photos", [])),
        "published": bool(data.get("published", True)),
        "availability": availability,
        "estado": availability,
        "closure_reason": closure_reason,
        "motivo_cierre": closure_reason,
        "version": int(data.get("version", 1)),
        "has_pending_proposal": has_pending_proposal,
        "can_edit": can_edit,
        "can_pause": can_pause,
        "can_reactivate": can_reactivate,
        "can_withdraw": can_withdraw,
        "actions": actions,
        "available_actions": actions,
        "created_at": timestamp(data["created_at"]) if data.get("created_at") else None,
        "updated_at": timestamp(data["updated_at"]) if data.get("updated_at") else (timestamp(data["created_at"]) if data.get("created_at") else None),
    }


def get_seller_management_listings(uid):
    client = firestore.client(app=get_app())
    snapshots = list(_listings().stream())
    owned = []
    for snap in snapshots:
        d = snap.to_dict()
        if d.get("published") is True and d.get("seller_uid") == uid:
            owned.append((snap.id, d))
    if not owned:
        return []
    control_refs = [_selection_ref(client, lid) for lid, _ in owned]
    controls = {snap.id: snap.to_dict() for snap in client.get_all(control_refs) if snap.exists}
    results = []
    for lid, data in owned:
        ctrl = controls.get(lid, {})
        has_pending = bool(ctrl.get("pending_proposal_id"))
        results.append(serialize_management_listing(lid, data, has_pending_proposal=has_pending))
    return results


def get_listing_for_management(seller_uid, listing_id):
    client = firestore.client(app=get_app())
    snap = client.collection(LISTINGS_COLLECTION).document(listing_id).get()
    if not snap.exists or snap.to_dict().get("seller_uid") != seller_uid:
        raise ProposalNotFound()
    data = snap.to_dict()
    ctrl = _selection_ref(client, listing_id).get().to_dict() or {}
    has_pending = bool(ctrl.get("pending_proposal_id"))
    return serialize_management_listing(listing_id, data, has_pending_proposal=has_pending)


def pause_listing(seller_uid, listing_id, expected_version=None):
    client = _selection_client()
    def write(tx):
        ref, listing = _owned_listing(tx, client, listing_id, seller_uid)
        control = _selection_ref(client, listing_id).get(transaction=tx).to_dict() or {}
        current_availability = listing_availability(listing)
        current_version = int(listing.get("version", 1))
        if current_availability == "PAUSED":
            return {"id": listing_id, "availability": "PAUSED", "version": current_version}
        if current_availability == "CLOSED":
            raise DecisionConflict()
        if control.get("pending_proposal_id"):
            raise DecisionConflict()
        if expected_version is not None and expected_version != current_version:
            raise VersionConflict()
        new_version = current_version + 1
        tx.update(ref, {
            "availability": "PAUSED",
            "version": new_version,
            "updated_at": firestore.SERVER_TIMESTAMP,
        })
        return {"id": listing_id, "availability": "PAUSED", "version": new_version}
    return _run_selection_transaction(client, write)


def reactivate_listing(seller_uid, listing_id, expected_version=None):
    client = _selection_client()
    def write(tx):
        ref, listing = _owned_listing(tx, client, listing_id, seller_uid)
        control = _selection_ref(client, listing_id).get(transaction=tx).to_dict() or {}
        current_availability = listing_availability(listing)
        current_version = int(listing.get("version", 1))
        if current_availability == "ACTIVE":
            return {"id": listing_id, "availability": "ACTIVE", "version": current_version}
        if current_availability == "CLOSED":
            raise DecisionConflict()
        if control.get("pending_proposal_id"):
            raise DecisionConflict()
        if expected_version is not None and expected_version != current_version:
            raise VersionConflict()
        new_version = current_version + 1
        tx.update(ref, {
            "availability": "ACTIVE",
            "version": new_version,
            "updated_at": firestore.SERVER_TIMESTAMP,
        })
        return {"id": listing_id, "availability": "ACTIVE", "version": new_version}
    return _run_selection_transaction(client, write)


def withdraw_listing(seller_uid, listing_id, expected_version=None):
    from google.cloud.firestore_v1.base_query import FieldFilter
    client = _selection_client()
    def write(tx):
        ref, listing = _owned_listing(tx, client, listing_id, seller_uid)
        control = _selection_ref(client, listing_id).get(transaction=tx).to_dict() or {}
        current_availability = listing_availability(listing)
        current_version = int(listing.get("version", 1))
        current_closure = listing.get("closure_reason")
        if current_availability == "CLOSED":
            if current_closure == "WITHDRAWN":
                return {"id": listing_id, "availability": "CLOSED", "closure_reason": "WITHDRAWN", "version": current_version}
            raise DecisionConflict()
        if control.get("pending_proposal_id"):
            raise DecisionConflict()
        if expected_version is not None and expected_version != current_version:
            raise VersionConflict()
        query = client.collection(MATCHES_COLLECTION).where(filter=FieldFilter("listing_id", "==", listing_id))
        recipients = {m["buyer_uid"] for snap in query.stream(transaction=tx)
                      if (m := snap.to_dict()).get("status", "PENDING") in {"PENDING", "CONFIRMED"}}
        new_version = current_version + 1
        tx.update(ref, {
            "availability": "CLOSED",
            "closure_reason": "WITHDRAWN",
            "closed_at": firestore.SERVER_TIMESTAMP,
            "version": new_version,
            "updated_at": firestore.SERVER_TIMESTAMP,
        })
        _closure_notices(tx, client, listing_id, listing.get("title", ""), recipients, closure_reason="WITHDRAWN")
        return {"id": listing_id, "availability": "CLOSED", "closure_reason": "WITHDRAWN", "version": new_version}

    result = _run_selection_transaction(client, write)
    try:
        process_selection_notifications(limit=10, listing_id=listing_id)
    except Exception as error:
        logger.error("Pendientes avisos duraderos de retirada (%s).", type(error).__name__)
    return result


def update_listing_full(seller_uid, listing_id, values, new_photos=None, retained_photos=None, expected_version=None):
    uploaded_blobs = []
    new_photo_urls = []
    if new_photos:
        container = get_container_client()
        for photo in new_photos:
            name = f"{seller_uid}/{uuid4().hex}"
            blob = container.get_blob_client(name)
            uploaded_blobs.append(blob)
            try:
                photo.seek(0)
                blob.upload_blob(
                    photo,
                    length=photo.size,
                    overwrite=True,
                    content_settings=ContentSettings(content_type=photo.content_type),
                )
                new_photo_urls.append(blob.url)
            except Exception:
                _cleanup_uploaded(uploaded_blobs)
                raise

    client = _selection_client()
    removed_photos = []

    def write(tx):
        nonlocal removed_photos
        ref, listing = _owned_listing(tx, client, listing_id, seller_uid)
        control = _selection_ref(client, listing_id).get(transaction=tx).to_dict() or {}
        if control.get("pending_proposal_id") or control.get("accepted_proposal_id") or listing_availability(listing) == "CLOSED":
            raise DecisionConflict()
        current_version = int(listing.get("version", 1))
        if expected_version is not None and expected_version != current_version:
            raise VersionConflict()

        current_photos = list(listing.get("photos", []))
        if retained_photos is not None:
            for p in retained_photos:
                if p not in current_photos:
                    raise InvalidPhotos("La fotografía conservada no pertenece al anuncio.")
            final_photos = list(retained_photos) + new_photo_urls
        elif new_photo_urls:
            final_photos = current_photos + new_photo_urls
        else:
            final_photos = current_photos

        if not final_photos:
            raise InvalidPhotos("El anuncio debe conservar al menos una fotografía válida.")
        if len(final_photos) > 10:
            raise InvalidPhotos("Se permiten como máximo 10 fotografías.")

        removed_photos = [p for p in current_photos if p not in final_photos]
        new_version = current_version + 1
        update_data = {
            **values,
            "photos": final_photos,
            "version": new_version,
            "updated_at": firestore.SERVER_TIMESTAMP,
        }
        tx.update(ref, update_data)

    try:
        _run_selection_transaction(client, write)
    except Exception:
        _cleanup_uploaded(uploaded_blobs)
        raise

    for p in removed_photos:
        _cleanup_removed_blob(p)

    return get_listing(listing_id)
