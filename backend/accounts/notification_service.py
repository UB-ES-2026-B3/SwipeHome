"""Contrato de avisos US4 y compatibilidad de lectura con avisos históricos."""
from . import repository
from .pagination import InvalidQuery as InvalidNotificationQuery
from .pagination import page_result, parse_query as _parse_query, timestamp

CURSOR_SALT = "accounts.notifications.v1"


def parse_query(params, uid):
    return _parse_query(params, uid, salt=CURSOR_SALT)


def list_notifications(user, params):
    limit, position = parse_query(params, user.uid)
    records = repository.get_notifications(user.uid, limit=limit + 1, position=position)
    items = []
    for row in records:
        item = {
            "id": row["id"], "type": row["type"], "message": row["message"],
            "created_at": timestamp(row["created_at"]),
        }
        # No se inventan matches ni identidades para avisos previos a US4.
        if "match_id" in row:
            item.update({
                "match_id": row["match_id"],
                "buyer": {"id": row["buyer_uid"], "name": row["buyer_name"]},
                "listing": {"id": row["listing_id"], "title": row["listing_title"]},
            })
        items.append(item)
    return page_result(items, limit, user.uid, salt=CURSOR_SALT)
