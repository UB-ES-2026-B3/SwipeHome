import os
from tempfile import TemporaryDirectory
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
# Only for local development. No cloud credentials are required.
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "swipehome-local-development-only")
DEBUG = False
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "testserver"]
INSTALLED_APPS = ["django.contrib.auth", "django.contrib.contenttypes", "accounts"]
MIDDLEWARE = ["django.middleware.security.SecurityMiddleware", "django.middleware.common.CommonMiddleware"]
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
