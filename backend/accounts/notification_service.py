"""Validación, cursores y contrato público de la consulta de avisos."""
import re
from datetime import timezone

from django.core import signing
from google.api_core.datetime_helpers import DatetimeWithNanoseconds

from . import repository

CURSOR_SALT = "accounts.notifications.v1"


class InvalidNotificationQuery(ValueError):
    pass


def timestamp(value):
    # Firestore conserva nanosegundos: no truncarlos en el desempate del cursor.
    if isinstance(value, DatetimeWithNanoseconds):
        return value.rfc3339()
    if value.tzinfo is None:
        raise ValueError("Fecha sin zona horaria.")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_query(params, uid):
    if set(params) - {"limit", "cursor"} or any(len(params.getlist(k)) != 1 for k in params):
        raise InvalidNotificationQuery()
    raw_limit = params.get("limit", "20")
    if not re.fullmatch(r"[0-9]{1,2}", raw_limit) or not 1 <= int(raw_limit) <= 50:
        raise InvalidNotificationQuery()
    position = None
    if "cursor" in params:
        raw_cursor = params["cursor"]
        if not raw_cursor or len(raw_cursor) > 4096:
            raise InvalidNotificationQuery()
        try:
            data = signing.loads(raw_cursor, salt=CURSOR_SALT)
            if not isinstance(data, dict) or set(data) != {"uid", "id", "created_at"}:
                raise ValueError()
            if data["uid"] != uid or not isinstance(data["id"], str):
                raise ValueError()
            if not data["id"] or "/" in data["id"] or data["id"] in {".", ".."}:
                raise ValueError()
            if not isinstance(data["created_at"], str):
                raise ValueError()
            position = (DatetimeWithNanoseconds.from_rfc3339(data["created_at"]), data["id"])
        except (signing.BadSignature, ValueError, TypeError, KeyError, OverflowError):
            raise InvalidNotificationQuery() from None
    return int(raw_limit), position


def list_notifications(user, params):
    limit, position = parse_query(params, user.uid)
    records = repository.get_notifications(user.uid, limit=limit + 1, position=position)
    page = records[:limit]
    items = [
        {"id": row["id"], "type": row["type"], "message": row["message"],
         "created_at": timestamp(row["created_at"])}
        for row in page
    ]
    next_cursor = None
    if len(records) > limit:
        last = items[-1]
        next_cursor = signing.dumps(
            {"uid": user.uid, "id": last["id"], "created_at": last["created_at"]},
            salt=CURSOR_SALT,
        )
    return {"items": items, "next_cursor": next_cursor}
