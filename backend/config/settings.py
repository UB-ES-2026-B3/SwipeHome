import os
from tempfile import TemporaryDirectory
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
# Only for local development. No cloud credentials are required.
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "swipehome-local-development-only")

# DJANGO_DEV=1  →  HTTP local (runserver), cookies sin Secure, DEBUG activo.
# Sin DJANGO_DEV  →  HTTPS local (runhttps) o producción; cookies Secure.
_DEV = os.environ.get("DJANGO_DEV", "").strip() == "1"

DEBUG = _DEV
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "testserver"]
# Render inyecta RENDER_EXTERNAL_HOSTNAME con el dominio publico del servicio.
# En local no existe y ALLOWED_HOSTS se queda como estaba.
_RENDER_HOST = os.environ.get("RENDER_EXTERNAL_HOSTNAME")
if _RENDER_HOST:
    ALLOWED_HOSTS.append(_RENDER_HOST)
# Hosts adicionales separados por comas (opcional).
ALLOWED_HOSTS += [h.strip() for h in os.environ.get("ALLOWED_HOSTS", "").split(",") if h.strip()]

# Render termina el TLS en su proxy y reenvia a Django por HTTP. Sin esto
# Django cree que la peticion es insegura y rechaza las cookies Secure.
if _RENDER_HOST:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

INSTALLED_APPS = ["django.contrib.auth", "django.contrib.contenttypes", "django.contrib.sessions", "accounts"]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
]
SESSION_ENGINE = "django.contrib.sessions.backends.db"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SECURE = not _DEV   # False en HTTP local, True en HTTPS/producción
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_SAVE_EVERY_REQUEST = False
ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
TEST_DATABASE_DIR = TemporaryDirectory(prefix="swipehome-tests-")
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": os.environ.get("DATABASE_PATH", str(BASE_DIR / "db.sqlite3")),
        "OPTIONS": {"timeout": 20, "transaction_mode": "IMMEDIATE"},
        "TEST": {"NAME": str(Path(TEST_DATABASE_DIR.name) / "test.sqlite3")},
    }
}
AUTH_USER_MODEL = "accounts.User"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
PASSWORD_HASHERS = ["django.contrib.auth.hashers.PBKDF2PasswordHasher"]
USE_TZ = True
STATIC_URL = "/static/"
