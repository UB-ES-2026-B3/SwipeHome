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
        seller_uids = {
            r.get("seller_uid") or (listing_snaps[r["listing_id"]].to_dict().get("seller_uid") if r["listing_id"] in listing_snaps else None)
            for r in records
        }
        seller_uids.discard(None)
        seller_refs = [
            client.collection(repository.USERS_COLLECTION).document(suid)
            for suid in seller_uids
        ]
        seller_snaps = {
            snap.id: snap.to_dict()
            for snap in client.get_all(seller_refs)
            if snap.exists
        } if seller_refs else {}
        for r in records:
            snap = listing_snaps.get(r["listing_id"])
            listing_data = snap.to_dict() if snap else None
            seller_uid = r.get("seller_uid") or (listing_data.get("seller_uid") if listing_data else "")
            seller_name = ""
            if seller_uid and seller_uid in seller_snaps:
                seller_name = seller_snaps[seller_uid].get("name", "")
            if not seller_name and seller_uid:
                try:
                    prof = repository.get_user_profile(seller_uid)
                    if prof:
                        seller_name = prof.get("name", "")
                except Exception:
                    pass
            listing_obj = listing_item(snap.id, listing_data) if (snap and published_listing(listing_data)) else {
                "id": r["listing_id"],
                "title": r.get("listing_title", ""),
            }
            listing_obj["availability"] = repository.listing_availability(listing_data) if listing_data else "CLOSED"
            listing_obj["closure_reason"] = listing_data.get("closure_reason") if listing_data else None
            if seller_name:
                listing_obj["seller_name"] = seller_name
            item = {
                "id": r["id"],
                "status": "CONFIRMED",
                "confirmed_at": timestamp(r["confirmed_at"]),
                "created_at": timestamp(r["created_at"]) if r.get("created_at") else None,
                "seller": {
                    "id": seller_uid or "",
                    "name": seller_name,
                },
                "listing": listing_obj,
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
                    "availability": r.get("availability", "ACTIVE"),
                    "closure_reason": r.get("closure_reason"),
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
