"""Cursores firmados por usuario y recurso, con precisión Firestore."""
import re
from datetime import timezone

from django.core import signing
from google.api_core.datetime_helpers import DatetimeWithNanoseconds


class InvalidQuery(ValueError):
    pass


def timestamp(value):
    if isinstance(value, DatetimeWithNanoseconds):
        return value.rfc3339()
    if value.tzinfo is None:
        raise ValueError("Fecha sin zona horaria.")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def valid_document_id(value):
    return (
        isinstance(value, str) and bool(value) and "/" not in value
        and value not in {".", ".."} and len(value.encode("utf-8")) <= 1500
    )


def parse_query(params, uid, *, salt):
    if set(params) - {"limit", "cursor"} or any(len(params.getlist(k)) != 1 for k in params):
        raise InvalidQuery()
    raw_limit = params.get("limit", "20")
    if not re.fullmatch(r"[0-9]{1,2}", raw_limit) or not 1 <= int(raw_limit) <= 50:
        raise InvalidQuery()
    position = None
    if "cursor" in params:
        raw_cursor = params["cursor"]
        if not raw_cursor or len(raw_cursor) > 4096:
            raise InvalidQuery()
        try:
            data = signing.loads(raw_cursor, salt=salt)
            if not isinstance(data, dict) or set(data) != {"uid", "id", "created_at"}:
                raise ValueError()
            if data["uid"] != uid or not valid_document_id(data["id"]):
                raise ValueError()
            if not isinstance(data["created_at"], str):
                raise ValueError()
            position = (DatetimeWithNanoseconds.from_rfc3339(data["created_at"]), data["id"])
        except (signing.BadSignature, ValueError, TypeError, KeyError, OverflowError):
            raise InvalidQuery() from None
    return int(raw_limit), position


def page_result(records, limit, uid, *, salt):
    page = records[:limit]
    cursor = None
    if len(records) > limit:
        last = page[-1]
        cursor = signing.dumps(
            {"uid": uid, "id": last["id"], "created_at": last["created_at"]},
            salt=salt,
        )
    return {"items": page, "next_cursor": cursor}
