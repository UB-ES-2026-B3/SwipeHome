"""Listas y transiciones del ciclo de candidaturas US5."""
from accounts import repository
from accounts.pagination import page_result, parse_query, timestamp

MATCHES_CURSOR_SALT = "properties.matches.v1"
CANDIDATES_CURSOR_SALT = "properties.candidates.v1"


def list_matches(user, params):
    limit, position = parse_query(params, user.uid, salt=MATCHES_CURSOR_SALT)
    records = repository.get_confirmed_matches(
        user.uid, user.role, limit=limit + 1, position=position,
    )
    for record in records:
        record["created_at"] = timestamp(record["created_at"])
    return page_result(records, limit, user.uid, salt=MATCHES_CURSOR_SALT)


def list_candidates(user, params):
    limit, position = parse_query(params, user.uid, salt=CANDIDATES_CURSOR_SALT)
    records = repository.get_pending_candidates(user.uid, limit=limit + 1, position=position)
    for record in records:
        record["created_at"] = timestamp(record["created_at"])
    return page_result(records, limit, user.uid, salt=CANDIDATES_CURSOR_SALT)


def decide_candidate(user, decision_id, value):
    if not isinstance(value, str) or value not in {"ACCEPT", "REJECT"}:
        raise ValueError("Decisión de Vendedor inválida.")
    decision, match, created = repository.transition_seller_decision(
        user.uid, decision_id, value,
    )
    return {
        "decision": {
            "id": decision["id"], "listing_id": decision["listing_id"],
            "buyer_uid": decision["buyer_uid"], "value": decision["value"],
            "seller_decision": decision["seller_decision"],
            "created_at": timestamp(decision["created_at"]),
            "seller_decided_at": timestamp(decision["seller_decided_at"]),
        },
        "match": None if match is None else {
            "id": match["id"], "decision_id": match["decision_id"],
            "listing_id": match["listing_id"], "created_at": timestamp(match["created_at"]),
        },
    }, 201 if created else 200
