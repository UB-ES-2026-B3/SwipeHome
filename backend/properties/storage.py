from pathlib import Path
from uuid import uuid4


MAX_PHOTOS = 10
MAX_PHOTO_SIZE = 5 * 1024 * 1024
ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}


def _read_upload(upload):
    if upload.size > MAX_PHOTO_SIZE:
        raise ValueError("Cada fotografía puede ocupar como máximo 5 MB.")
    content = upload.read()
    upload.seek(0)
    return content


def validate_photo(upload):
    if upload is None:
        raise ValueError("La fotografía no es válida.")
    if getattr(upload, "content_type", None) not in ALLOWED_CONTENT_TYPES:
        raise ValueError("El formato de la fotografía no está permitido.")
    content = _read_upload(upload)
    valid = (
        (content.startswith(b"\xff\xd8\xff") and content.endswith(b"\xff\xd9"))
        or (content.startswith(b"\x89PNG\r\n\x1a\n") and b"IEND" in content[-32:])
        or (
            content.startswith(b"RIFF")
            and content[8:12] == b"WEBP"
            and content[12:16] in (b"VP8 ", b"VP8L", b"VP8X")
        )
    )
    if not valid:
        raise ValueError("El contenido de la fotografía no es una imagen válida.")


def generated_name(upload):
    suffix = Path(upload.name or "").suffix.lower()
    return f"properties/{uuid4().hex}{suffix}"
