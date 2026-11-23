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


def get_buyer_preferences(uid) -> dict:
    """Obtiene filtros privados del Comprador; perfiles antiguos empiezan vacíos."""
    snapshot = _users().document(uid).get()
    if not snapshot.exists:
        raise ValueError("No existe el perfil del Comprador.")
    from properties.preferences import (
        DEFAULT_FILTERS,
        validate_filters,
        validate_stored_filters,
    )

    preferences = snapshot.to_dict().get("preferences")
    if preferences is None:
        return validate_filters(DEFAULT_FILTERS)
    return validate_stored_filters(preferences)


def update_buyer_preferences(uid, preferences) -> None:
    """Reemplaza solo los filtros del usuario autenticado en una escritura."""
    reference = _users().document(uid)
    snapshot = reference.get()
    if not snapshot.exists:
        raise ValueError("No existe el perfil del Comprador.")
    reference.update({"preferences": preferences})


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


# Avisos de interés y confirmación; los destinatarios se verifican en cada consulta.
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
        elif data["type"].startswith("SELECTION_"):
            fields = ("listing_id", "listing_title")
            if data["type"] != "SELECTION_UNAVAILABLE":
                fields += ("selection_id",)
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
SELECTIONS_COLLECTION = "selections"


class ListingNotFound(Exception):
    pass


class DecisionConflict(Exception):
    pass


class SelectionNotFound(Exception):
    pass


class SelectionConflict(Exception):
    pass


class SelectionForbidden(Exception):
    pass


class InconsistentDecision(RuntimeError):
    """Datos fuera del contrato: nunca devolver éxito ni repararlos silenciosamente."""


SELECTION_RESPONSES = {"ACCEPT": "ACCEPTED", "REJECT": "REJECTED", "CANCEL": "CANCELLED"}


def selection_key(listing_id, idempotency_key):
    data = json.dumps([listing_id, idempotency_key], ensure_ascii=True)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def _run_selection_transaction(client, write, *args):
    import random
    import time

    from google.api_core.exceptions import Aborted, AlreadyExists

    operation = firestore.transactional(write)
    for attempt in range(5):
        try:
            return operation(client.transaction(max_attempts=10), *args)
        except (Aborted, AlreadyExists):
            if attempt == 4:
                raise
        except ValueError as error:
            if not isinstance(error.__cause__, Aborted) or attempt == 4:
                raise
        time.sleep(random.uniform(0.02, min(0.5, 0.05 * (2 ** attempt))))


def create_selection(seller_uid, seller_name, listing_id, buyer_uid, idempotency_key):
    """Crea una propuesta distinta por intención y excluye las simultáneas."""
    client = firestore.client(app=get_app())
    selection_ref = client.collection(SELECTIONS_COLLECTION).document(
        selection_key(listing_id, idempotency_key)
    )
    return _run_selection_transaction(
        client, _create_selection, client, selection_ref, seller_uid, seller_name, listing_id, buyer_uid,
    )


def _create_selection(transaction, client, selection_ref, seller_uid, seller_name, listing_id, buyer_uid):
    from datetime import datetime, timezone
    from properties.serialization import published_listing

    listing_ref = client.collection(LISTINGS_COLLECTION).document(listing_id)
    listing = listing_ref.get(transaction=transaction).to_dict()
    if listing is None or listing.get("seller_uid") != seller_uid:
        raise SelectionNotFound()

    previous = selection_ref.get(transaction=transaction)
    if previous.exists:
        selection = previous.to_dict()
        if selection["seller_uid"] != seller_uid or selection["buyer_uid"] != buyer_uid:
            raise SelectionConflict()
        return {"id": previous.id, **selection}, False

    if listing.get("pending_selection_id") or listing.get("selected_selection_id"):
        raise SelectionConflict()
    if not published_listing(listing):
        raise ListingNotFound()

    match_id = decision_key(buyer_uid, listing_id)
    match = client.collection(MATCHES_COLLECTION).document(match_id).get(transaction=transaction).to_dict()
    decision = client.collection(SWIPES_COLLECTION).document(match_id).get(transaction=transaction).to_dict()
    if match is None or decision is None or (
        match.get("buyer_uid") != buyer_uid
        or match.get("seller_uid", seller_uid) != seller_uid
        or match.get("listing_id") != listing_id
        or match.get("decision_id") != match_id
        or decision.get("buyer_uid") != buyer_uid
        or decision.get("listing_id") != listing_id
        or decision.get("seller_uid", seller_uid) != seller_uid
        or decision.get("value") != "LIKE"
        or decision.get("seller_decision") not in {"ACCEPT", None}
    ):
        raise SelectionNotFound()

    created_at = datetime.now(timezone.utc)
    selection = {
        "listing_id": listing_id,
        "listing_title": listing["title"],
        "seller_uid": seller_uid,
        "seller_name": seller_name,
        "buyer_uid": buyer_uid,
        "match_id": match_id,
        "status": "PENDING",
        "created_at": created_at,
        "updated_at": created_at,
    }
    transaction.create(selection_ref, selection)
    transaction.update(listing_ref, {"pending_selection_id": selection_ref.id})
    _write_selection_notice(
        transaction, client, selection_ref.id, selection, buyer_uid, "PROPOSAL",
        "El propietario te ha enviado una propuesta de selección.",
    )
    return {"id": selection_ref.id, **selection}, True


def get_selection(uid, role, selection_id):
    client = firestore.client(app=get_app())
    read = firestore.transactional(_read_selection)
    return read(client.transaction(read_only=True), client, uid, role, selection_id)


def _read_selection(transaction, client, uid, role, selection_id):
    snapshot = client.collection(SELECTIONS_COLLECTION).document(selection_id).get(transaction=transaction)
    selection = snapshot.to_dict()
    field = "buyer_uid" if role == "BUYER" else "seller_uid"
    if selection is None or selection.get(field) != uid:
        raise SelectionNotFound()
    listing_ref = client.collection(LISTINGS_COLLECTION).document(selection["listing_id"])
    listing = listing_ref.get(transaction=transaction).to_dict()
    if listing is None or listing.get("seller_uid") != selection["seller_uid"]:
        raise SelectionNotFound()
    return {"id": snapshot.id, **selection}, listing


def list_selections(uid, role, *, limit, position=None):
    from google.cloud.firestore_v1.base_query import FieldFilter

    collection = firestore.client(app=get_app()).collection(SELECTIONS_COLLECTION)
    field = "buyer_uid" if role == "BUYER" else "seller_uid"
    query = (
        collection.where(filter=FieldFilter(field, "==", uid))
        .order_by("created_at", direction=firestore.Query.DESCENDING)
        .order_by("__name__", direction=firestore.Query.DESCENDING)
    )
    if position is not None:
        query = query.start_after({
            "created_at": position[0], "__name__": collection.document(position[1]),
        })
    return [{"id": snapshot.id, **snapshot.to_dict()} for snapshot in query.limit(limit).stream()]


def transition_selection(user_uid, role, selection_id, action):
    client = firestore.client(app=get_app())
    selection_ref = client.collection(SELECTIONS_COLLECTION).document(selection_id)
    return _run_selection_transaction(
        client, _transition_selection, client, selection_ref, user_uid, role, action,
    )


def _transition_selection(transaction, client, selection_ref, user_uid, role, action):
    from datetime import datetime, timezone
    from properties.serialization import published_listing

    snapshot = selection_ref.get(transaction=transaction)
    selection = snapshot.to_dict()
    if selection is None:
        raise SelectionNotFound()
    allowed = (
        role == "BUYER" and action in {"ACCEPT", "REJECT"} and selection["buyer_uid"] == user_uid
        or role == "SELLER" and action == "CANCEL" and selection["seller_uid"] == user_uid
    )
    if not allowed:
        raise SelectionForbidden()

    target_status = SELECTION_RESPONSES[action]
    if selection["status"] == target_status:
        return {"id": snapshot.id, **selection}, False
    if selection["status"] != "PENDING":
        raise SelectionConflict()

    listing_ref = client.collection(LISTINGS_COLLECTION).document(selection["listing_id"])
    listing = listing_ref.get(transaction=transaction).to_dict()
    if listing is None or listing.get("seller_uid") != selection["seller_uid"]:
        raise SelectionNotFound()
    if listing.get("pending_selection_id") != snapshot.id:
        raise InconsistentDecision("El anuncio no referencia a su propuesta pendiente.")
    if action == "ACCEPT" and (not published_listing(listing) or listing.get("selected_selection_id")):
        raise SelectionConflict()

    affected = _selection_affected_buyers(transaction, client, selection) if action == "ACCEPT" else set()
    changes = {"status": target_status, "updated_at": datetime.now(timezone.utc)}
    updated = {**selection, **changes}
    listing_changes = {"pending_selection_id": firestore.DELETE_FIELD}
    if action == "ACCEPT":
        listing_changes.update({
            "published": False,
            "available": False,
            "selected_buyer_uid": selection["buyer_uid"],
            "selected_selection_id": snapshot.id,
            "selected_at": changes["updated_at"],
        })
    transaction.update(selection_ref, changes)
    transaction.update(listing_ref, listing_changes)

    if action == "ACCEPT":
        _write_selection_notice(
            transaction, client, snapshot.id, updated, selection["seller_uid"], target_status,
            "El comprador ha aceptado la propuesta y la vivienda ha quedado cerrada.",
        )
        _write_selection_notice(
            transaction, client, snapshot.id, updated, selection["buyer_uid"], target_status,
            "Has aceptado la propuesta y la vivienda ha quedado cerrada.",
        )
        for buyer_uid in sorted(affected):
            _write_selection_notice(
                transaction, client, snapshot.id, updated, buyer_uid, "UNAVAILABLE",
                "La vivienda ya no está disponible.",
            )
    elif action == "REJECT":
        _write_selection_notice(
            transaction, client, snapshot.id, updated, selection["seller_uid"], target_status,
            "El comprador ha rechazado la propuesta.",
        )
    else:
        _write_selection_notice(
            transaction, client, snapshot.id, updated, selection["buyer_uid"], target_status,
            "El propietario ha cancelado la propuesta.",
        )
    return {"id": snapshot.id, **updated}, True


def _selection_affected_buyers(transaction, client, selection):
    from google.cloud.firestore_v1.base_query import FieldFilter

    listing_id = selection["listing_id"]
    seller_uid = selection["seller_uid"]
    by_listing = FieldFilter("listing_id", "==", listing_id)
    matches = client.collection(MATCHES_COLLECTION).where(filter=by_listing)
    candidates = client.collection(SWIPES_COLLECTION).where(filter=by_listing)
    affected = set()
    for snapshot in matches.stream(transaction=transaction):
        match = snapshot.to_dict()
        uid = match.get("buyer_uid")
        if (
            isinstance(uid, str) and uid
            and match.get("seller_uid", seller_uid) == seller_uid
            and match.get("decision_id") == snapshot.id == decision_key(uid, listing_id)
        ):
            affected.add(uid)
    for snapshot in candidates.stream(transaction=transaction):
        candidate = snapshot.to_dict()
        uid = candidate.get("buyer_uid")
        if (
            isinstance(uid, str) and uid
            and candidate.get("seller_uid") == seller_uid
            and candidate.get("value") == "LIKE"
            and candidate.get("seller_decision") == "PENDING"
            and snapshot.id == decision_key(uid, listing_id)
        ):
            affected.add(uid)
    affected.discard(selection["buyer_uid"])
    return affected


def _write_selection_notice(transaction, client, selection_id, selection, recipient, event, message):
    notice_key = hashlib.sha256(json.dumps([selection_id, recipient]).encode("utf-8")).hexdigest()
    notice_ref = client.collection(NOTIFICATIONS_COLLECTION).document(
        f"selection-{event.lower()}-{notice_key}"
    )
    notice = {
        "recipient_uid": recipient,
        "type": "SELECTION_" + event,
        "message": message,
        "listing_id": selection["listing_id"],
        "listing_title": selection["listing_title"],
        "created_at": selection["updated_at"],
    }
    if event != "UNAVAILABLE":
        notice["selection_id"] = selection_id
    transaction.create(notice_ref, notice)


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
            seller_decision = decision.get("seller_decision")
            if seller_decision is None and snapshots["match"].exists:
                # Previously confirmed US4 records remain confirmed after the
                # additive US5 transition is deployed.
                seller_decision = "ACCEPT"
            if seller_decision not in {"PENDING", "ACCEPT", "REJECT"}:
                raise InconsistentDecision()
            if decision.get("seller_uid", listing["seller_uid"]) != listing["seller_uid"]:
                raise InconsistentDecision()
            if seller_decision == "ACCEPT":
                if (
                    not snapshots["match"].exists
                    or match.get("buyer_uid") != buyer_uid or match.get("listing_id") != listing_id
                    or match.get("seller_uid", listing["seller_uid"]) != listing["seller_uid"]
                    or match.get("decision_id") != key
                ):
                    raise InconsistentDecision()
            elif snapshots["match"].exists:
                raise InconsistentDecision()
        elif snapshots["match"].exists or snapshots["notice"].exists:
            raise InconsistentDecision()
        return {"id": key, **decision}, None if match is None else {"id": key, **match}, False
    if snapshots["match"].exists or snapshots["notice"].exists:
        raise InconsistentDecision()
    created_at = datetime.now(timezone.utc)
    decision = {
        "buyer_uid": buyer_uid, "listing_id": listing_id,
        "seller_uid": listing["seller_uid"], "buyer_name": buyer_name,
        "value": value, "created_at": created_at,
    }
    if value == "LIKE":
        decision["seller_decision"] = "PENDING"
    transaction.create(refs["decision"], decision)
    return {"id": key, **decision}, None, True


def transition_seller_decision(seller_uid, decision_id, value):
    """Atomically accept or reject an existing Buyer LIKE once."""
    import random
    import time

    from google.api_core.exceptions import Aborted, AlreadyExists
    from .pagination import valid_document_id

    if value not in {"ACCEPT", "REJECT"} or not valid_document_id(decision_id):
        raise ValueError("Decisión de Vendedor inválida.")
    client = firestore.client(app=get_app())
    refs = {
        "decision": client.collection(SWIPES_COLLECTION).document(decision_id),
        "match": client.collection(MATCHES_COLLECTION).document(decision_id),
        "listing": client.collection(LISTINGS_COLLECTION),
        "notice": client.collection(NOTIFICATIONS_COLLECTION).document("buyer-match-" + decision_id),
    }
    operation = firestore.transactional(_transition_seller_decision)
    for attempt in range(5):
        try:
            return operation(client.transaction(max_attempts=10), refs, seller_uid, value)
        except (Aborted, AlreadyExists):
            if attempt == 4:
                raise
        except ValueError as error:
            if not isinstance(error.__cause__, Aborted) or attempt == 4:
                raise
        time.sleep(random.uniform(0.02, min(0.5, 0.05 * (2 ** attempt))))


def _transition_seller_decision(transaction, refs, seller_uid, value):
    from datetime import datetime, timezone
    from properties.serialization import published_listing

    decision_snapshot = refs["decision"].get(transaction=transaction)
    if not decision_snapshot.exists:
        raise ListingNotFound()
    decision = decision_snapshot.to_dict()
    listing_ref = refs["listing"].document(
        decision.get("listing_id", "")
    )
    match_ref = refs["match"]
    notice_ref = refs["notice"]
    listing_snapshot = listing_ref.get(transaction=transaction)
    match_snapshot = match_ref.get(transaction=transaction)
    notice_snapshot = notice_ref.get(transaction=transaction)
    if not listing_snapshot.exists or not published_listing(listing_snapshot.to_dict()):
        raise ListingNotFound()
    listing = listing_snapshot.to_dict()
    if (
        decision.get("value") != "LIKE"
        or decision_key(decision.get("buyer_uid"), decision.get("listing_id")) != decision_snapshot.id
        or decision.get("seller_uid", listing.get("seller_uid")) != listing.get("seller_uid")
        or listing.get("seller_uid") != seller_uid
    ):
        raise ListingNotFound()

    state = decision.get("seller_decision")
    legacy_confirmed = state is None and match_snapshot.exists
    if legacy_confirmed:
        state = "ACCEPT"
    if state not in {"PENDING", "ACCEPT", "REJECT"}:
        raise InconsistentDecision()
    if state == value:
        match = match_snapshot.to_dict() if match_snapshot.exists else None
        if value == "ACCEPT" and (
            match is None
            or match.get("buyer_uid") != decision["buyer_uid"]
            or match.get("listing_id") != decision["listing_id"]
            or match.get("decision_id") != decision_snapshot.id
            or (not legacy_confirmed and not notice_snapshot.exists)
        ):
            raise InconsistentDecision()
        if value == "REJECT" and (match_snapshot.exists or notice_snapshot.exists):
            raise InconsistentDecision()
        return {"id": decision_snapshot.id, **decision}, (
            None if match is None else {"id": match_snapshot.id, **match}
        ), False
    if state != "PENDING":
        raise DecisionConflict()
    if match_snapshot.exists or notice_snapshot.exists:
        raise InconsistentDecision()

    decided_at = datetime.now(timezone.utc)
    updated = {**decision, "seller_decision": value, "seller_decided_at": decided_at}
    transaction.update(refs["decision"], {
        "seller_decision": value, "seller_decided_at": decided_at,
    })
    match = None
    if value == "ACCEPT":
        match = {
            "buyer_uid": decision["buyer_uid"], "seller_uid": seller_uid,
            "listing_id": decision["listing_id"], "decision_id": decision_snapshot.id,
            "created_at": decided_at,
        }
        transaction.create(match_ref, match)
        transaction.create(notice_ref, {
            "recipient_uid": decision["buyer_uid"], "match_id": decision_snapshot.id,
            "buyer_uid": decision["buyer_uid"], "buyer_name": decision["buyer_name"],
            "listing_id": decision["listing_id"], "listing_title": listing["title"],
            "type": "MATCH", "message": "El propietario ha confirmado tu interés.",
            "created_at": decided_at,
        })
    return {"id": decision_snapshot.id, **updated}, (
        None if match is None else {"id": decision_snapshot.id, **match}
    ), True


def get_pending_candidates(seller_uid, *, limit, position=None):
    from google.cloud.firestore_v1.base_query import FieldFilter
    from properties.serialization import listing_item, published_listing

    client = firestore.client(app=get_app())
    collection = client.collection(SWIPES_COLLECTION)
    query = (
        collection.where(filter=FieldFilter("seller_uid", "==", seller_uid))
        .where(filter=FieldFilter("value", "==", "LIKE"))
        .where(filter=FieldFilter("seller_decision", "==", "PENDING"))
        .order_by("created_at", direction=firestore.Query.DESCENDING)
        .order_by("__name__", direction=firestore.Query.DESCENDING)
    )
    candidates = []
    while len(candidates) < limit:
        bounded = query
        if position is not None:
            bounded = query.start_after({
                "created_at": position[0], "__name__": collection.document(position[1]),
            })
        snapshots = list(bounded.limit(limit).stream())
        for snapshot in snapshots:
            decision = snapshot.to_dict()
            position = (decision["created_at"], snapshot.id)
            listing = client.collection(LISTINGS_COLLECTION).document(decision["listing_id"]).get().to_dict()
            if (
                listing is None or listing.get("seller_uid") != seller_uid
                or not isinstance(decision.get("buyer_name"), str)
                or decision["seller_uid"] != seller_uid
                or decision["value"] != "LIKE"
                or decision["seller_decision"] != "PENDING"
                or decision_key(decision.get("buyer_uid"), decision.get("listing_id")) != snapshot.id
            ):
                raise InconsistentDecision()
            if listing.get("selected_selection_id"):
                continue
            if not published_listing(listing):
                raise InconsistentDecision()
            candidates.append({
                "id": snapshot.id,
                "buyer": {"id": decision["buyer_uid"], "name": decision["buyer_name"]},
                "listing": listing_item(decision["listing_id"], listing),
                "created_at": decision["created_at"],
            })
            if len(candidates) == limit:
                break
        if len(snapshots) < limit:
            break
    return candidates


def get_confirmed_matches(uid, role, *, limit, position=None):
    from google.cloud.firestore_v1.base_query import FieldFilter
    from properties.serialization import listing_available, listing_item

    if role not in {"BUYER", "SELLER"}:
        raise ValueError("Rol no válido.")
    field = "buyer_uid" if role == "BUYER" else "seller_uid"
    client = firestore.client(app=get_app())
    collection = client.collection(MATCHES_COLLECTION)
    query = (
        collection.where(filter=FieldFilter(field, "==", uid))
        .order_by("created_at", direction=firestore.Query.DESCENDING)
        .order_by("__name__", direction=firestore.Query.DESCENDING)
    )
    if position is not None:
        query = query.start_after({
            "created_at": position[0], "__name__": collection.document(position[1]),
        })
    matches = []
    for snapshot in query.limit(limit).stream():
        match = snapshot.to_dict()
        decision_snapshot = client.collection(SWIPES_COLLECTION).document(
            match["decision_id"]
        ).get()
        listing_snapshot = client.collection(LISTINGS_COLLECTION).document(
            match["listing_id"]
        ).get()
        decision = decision_snapshot.to_dict() if decision_snapshot.exists else None
        listing = listing_snapshot.to_dict() if listing_snapshot.exists else None
        match_seller = match.get("seller_uid", listing.get("seller_uid") if listing else None)
        if (
            decision is None or listing is None
            or decision.get("seller_decision") not in {"ACCEPT", None}
            or decision.get("value") != "LIKE"
            or match.get("decision_id") != snapshot.id
            or decision_key(match.get("buyer_uid"), match.get("listing_id")) != snapshot.id
            or decision.get("buyer_uid") != match.get("buyer_uid")
            or decision.get("listing_id") != match.get("listing_id")
            or decision.get("seller_uid", match_seller) != match_seller
            or listing.get("seller_uid") != match_seller
            or match.get(field) != uid
        ):
            raise InconsistentDecision()
        buyer_name = decision.get("buyer_name")
        if not isinstance(buyer_name, str) or not buyer_name:
            buyer = get_user_profile(match["buyer_uid"])
            if buyer is None:
                raise InconsistentDecision()
            buyer_name = buyer["name"]
        matches.append({
            "id": snapshot.id,
            "buyer": {"id": match["buyer_uid"], "name": buyer_name},
            "listing": {
                **listing_item(match["listing_id"], listing),
                "available": listing_available(listing),
            },
            **({"proposal_pending": bool(listing.get("pending_selection_id"))} if role == "SELLER" else {}),
            "created_at": match["created_at"],
        })
    return matches


def get_pending_listings(buyer_uid, *, limit, position=None, filters=None):
    """Recorre lotes con cursor y carga decisiones en batch, sin OFFSET ni N+1.

    Se busca un pendiente adicional. El cursor público siempre sale del último
    resultado ENTREGADO, nunca del último documento inspeccionado.
    """
    from google.cloud.firestore_v1.base_query import FieldFilter

    from properties.preferences import DEFAULT_FILTERS, matches_filters, validate_filters
    from properties.serialization import listing_item, published_listing

    if filters is None:
        filters = validate_filters(DEFAULT_FILTERS)
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
            if (
                decision_key(buyer_uid, snapshot.id) not in decisions
                and published_listing(data)
                and matches_filters(data, filters)
            ):
                records.append(listing_item(snapshot.id, data))
                if len(records) == limit:
                    break
        if len(snapshots) < batch_size:
            break
        last = snapshots[-1]
        position = (last.to_dict()["created_at"], last.id)
    return records
