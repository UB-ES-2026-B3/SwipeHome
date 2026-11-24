"""Consultas y decisiones de US4, siempre con identidad verificada."""
from accounts import repository
from accounts.pagination import page_result, parse_query, timestamp

CURSOR_SALT = "properties.explore.v1"


def explore(user, params):
    from .preferences import fingerprint
    preferences = repository.get_search_preferences(user.uid)
    salt = CURSOR_SALT + "." + fingerprint(preferences)
    limit, position = parse_query(params, user.uid, salt=salt)
    records = repository.get_pending_listings(
        user.uid, limit=limit + 1, position=position, preferences=preferences,
    )
    return page_result(records, limit, user.uid, salt=salt)


def decide(user, listing_id, value):
    if not isinstance(value, str) or value not in {"LIKE", "PASS"}:
        raise ValueError("Decisión inválida.")
    decision, match, created = repository.record_decision(
        user.uid, listing_id, value, buyer_name=user.name,
    )
    return {
        "decision": {
            "id": decision["id"], "listing_id": decision["listing_id"],
            "value": decision["value"], "created_at": timestamp(decision["created_at"]),
        },
        "match": None if match is None else {
            "id": match["id"], "decision_id": match["decision_id"],
            "listing_id": match["listing_id"], "status": match.get("status", "PENDING"),
            "created_at": timestamp(match["created_at"]),
        },
    }, 201 if created else 200
