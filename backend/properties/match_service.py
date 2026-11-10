"""Servicios de consulta y decisión de matches y candidaturas (US5)."""
from firebase_admin import firestore

from accounts import repository
from accounts.firebase import get_app
from accounts.pagination import (
    InvalidQuery,
    page_result,
    parse_query,
    timestamp,
    valid_document_id,
)
from properties.serialization import listing_item, published_listing

MATCHES_SALT = "properties.matches.v1"
CANDIDATES_SALT = "properties.candidates.v1"


class ForbiddenProperty(Exception):
    pass


def verify_property_relation(user, listing_id):
    client = firestore.client(app=get_app())
    if user.role == "SELLER":
        snap = client.collection(repository.LISTINGS_COLLECTION).document(listing_id).get()
        if not snap.exists or snap.to_dict().get("seller_uid") != user.uid:
            raise ForbiddenProperty()
    else:  # BUYER
        key = repository.decision_key(user.uid, listing_id)
        snap = client.collection(repository.SWIPES_COLLECTION).document(key).get()
        if not snap.exists or snap.to_dict().get("value") != "LIKE":
            raise ForbiddenProperty()


def list_matches(user, params):
    inmueble = params.get("inmueble")
    if inmueble is not None and not valid_document_id(inmueble):
        raise InvalidQuery()
    limit, position = parse_query(
        params,
        user.uid,
        salt=MATCHES_SALT,
        allowed_fields={"inmueble"},
        timestamp_field="confirmed_at",
    )
    if inmueble:
        verify_property_relation(user, inmueble)
    records = repository.get_confirmed_matches(
        user.uid,
        user.role,
        limit=limit + 1,
        position=position,
        listing_id=inmueble,
    )
    items = []
    if user.role == "BUYER":
        client = firestore.client(app=get_app())
        listing_refs = [
            client.collection(repository.LISTINGS_COLLECTION).document(r["listing_id"])
            for r in records[:limit + 1]
        ]
        listing_snaps = {
            snap.id: snap
            for snap in client.get_all(listing_refs)
            if snap.exists
        } if listing_refs else {}
        for r in records:
            snap = listing_snaps.get(r["listing_id"])
            listing_data = snap.to_dict() if snap else None
            item = {
                "id": r["id"],
                "status": "CONFIRMED",
                "confirmed_at": timestamp(r["confirmed_at"]),
                "created_at": timestamp(r["created_at"]) if r.get("created_at") else None,
                "listing": listing_item(snap.id, listing_data) if (snap and published_listing(listing_data)) else {
                    "id": r["listing_id"],
                    "title": r.get("listing_title", ""),
                },
            }
            items.append(item)
    else:  # SELLER
        for r in records:
            item = {
                "id": r["id"],
                "status": "CONFIRMED",
                "confirmed_at": timestamp(r["confirmed_at"]),
                "created_at": timestamp(r["created_at"]) if r.get("created_at") else None,
                "buyer": {
                    "id": r["buyer_uid"],
                    "name": r.get("buyer_name", ""),
                },
                "listing": {
                    "id": r["listing_id"],
                    "title": r.get("listing_title", ""),
                },
            }
            items.append(item)
    return page_result(
        items,
        limit,
        user.uid,
        salt=MATCHES_SALT,
        timestamp_field="confirmed_at",
    )


def list_candidates(user, params):
    inmueble = params.get("inmueble")
    if inmueble is not None and not valid_document_id(inmueble):
        raise InvalidQuery()
    limit, position = parse_query(
        params,
        user.uid,
        salt=CANDIDATES_SALT,
        allowed_fields={"inmueble"},
        timestamp_field="created_at",
    )
    if inmueble:
        verify_property_relation(user, inmueble)
    records = repository.get_candidates(
        user.uid,
        limit=limit + 1,
        position=position,
        listing_id=inmueble,
    )
    items = []
    for r in records:
        item = {
            "id": r["id"],
            "status": "PENDING",
            "created_at": timestamp(r["created_at"]),
            "buyer": {
                "id": r["buyer_uid"],
                "name": r.get("buyer_name", ""),
            },
            "listing": {
                "id": r["listing_id"],
                "title": r.get("listing_title", ""),
            },
        }
        items.append(item)
    return page_result(
        items,
        limit,
        user.uid,
        salt=CANDIDATES_SALT,
        timestamp_field="created_at",
    )


def decide_candidate(user, match_id, value):
    result, created = repository.record_seller_decision(user.uid, match_id, value)
    payload = {
        "id": result["id"],
        "status": result["status"],
        "decided_at": timestamp(result["decided_at"]),
    }
    if result.get("confirmed_at"):
        payload["confirmed_at"] = timestamp(result["confirmed_at"])
    return payload, 200
