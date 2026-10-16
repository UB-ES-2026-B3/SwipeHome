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

# En modo DEV, el frontend Vite (localhost:5173) hace de proxy hacia Django.
# El navegador envía Origin: http://localhost:5173, que Django rechaza porque
# no coincide con su propio host (127.0.0.1:8000).
# CSRF_TRUSTED_ORIGINS permite ese origen explícitamente en modo local.
CSRF_TRUSTED_ORIGINS = (
    ["http://localhost:5173", "http://127.0.0.1:5173"] if _DEV else []
)
INSTALLED_APPS = ["django.contrib.auth", "django.contrib.contenttypes", "django.contrib.sessions", "accounts"]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
]
SESSION_ENGINE = "django.contrib.sessions.backends.db"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SECURE = not _DEV   # False en HTTP local, True en HTTPS/producción
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_SAVE_EVERY_REQUEST = False
CSRF_COOKIE_SECURE = not _DEV      # False en HTTP local, True en HTTPS/producción
CSRF_COOKIE_SAMESITE = "Lax"
CSRF_FAILURE_VIEW = "accounts.views.csrf_failure"
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
