"""Contratos de lectura y escritura de propuestas."""
from accounts import repository
from accounts.pagination import page_result, parse_query, timestamp
from .serialization import listing_available, listing_item

CURSOR_SALT = "properties.selections.v1"


def selection_item(selection):
    return {
        "id": selection["id"],
        "status": selection["status"],
        "buyer_uid": selection["buyer_uid"],
        "seller": {"id": selection["seller_uid"], "name": selection["seller_name"]},
        "match_id": selection["match_id"],
        "listing": {"id": selection["listing_id"], "title": selection["listing_title"]},
        "created_at": timestamp(selection["created_at"]),
        "updated_at": timestamp(selection["updated_at"]),
    }


def selection_detail(user, selection_id):
    selection, listing = repository.get_selection(user.uid, user.role, selection_id)
    return {
        **selection_item(selection),
        "listing": {
            **listing_item(selection["listing_id"], listing),
            "available": listing_available(listing),
        },
    }


def list_selections(user, params):
    limit, position = parse_query(params, user.uid, salt=CURSOR_SALT)
    selections = repository.list_selections(user.uid, user.role, limit=limit + 1, position=position)
    return page_result([selection_item(row) for row in selections], limit, user.uid, salt=CURSOR_SALT)
