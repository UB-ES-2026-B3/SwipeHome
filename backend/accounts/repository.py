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
        "created_at": firestore.SERVER_TIMESTAMP,
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


class MatchNotFound(Exception):
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


def get_candidates(seller_uid, *, limit, position=None, listing_id=None):
    """Consulta paginada de candidatos PENDING de viviendas del Vendedor."""
    from google.cloud.firestore_v1.base_query import FieldFilter

    client = firestore.client(app=get_app())
    seller_listings_query = client.collection(LISTINGS_COLLECTION).where("seller_uid", "==", seller_uid)
    if listing_id:
        seller_listings_query = seller_listings_query.where("__name__", "==", listing_id)
    seller_listings = {doc.id: doc.to_dict() for doc in seller_listings_query.stream()}

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
        seller_listings_query = client.collection(LISTINGS_COLLECTION).where("seller_uid", "==", uid)
        if listing_id:
            seller_listings_query = seller_listings_query.where("__name__", "==", listing_id)
        seller_listings = {doc.id: doc.to_dict() for doc in seller_listings_query.stream()}

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
            "buyer_uid": data["buyer_uid"],
            "buyer_name": data.get("buyer_name", ""),
            "seller_uid": data.get("seller_uid", ""),
            "listing_id": data["listing_id"],
            "listing_title": data.get("listing_title", ""),
        })
    return records
