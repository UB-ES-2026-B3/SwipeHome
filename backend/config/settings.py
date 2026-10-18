import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
# El valor por defecto es solo para desarrollo local; en Render se define DJANGO_SECRET_KEY.
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "swipehome-local-development-only")

# DJANGO_DEV=1  →  desarrollo local, DEBUG activo.
# Sin DJANGO_DEV  →  producción, DEBUG desactivado.
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
# Django cree que la peticion es insegura (request.is_secure() es falso).
if _RENDER_HOST:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

INSTALLED_APPS = ["accounts"]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.common.CommonMiddleware",
]
ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
# Sin modelos ni sesiones, Django no necesita base de datos: los usuarios viven en
# Firebase Auth y los perfiles en Firestore (accounts/repository.py).
DATABASES = {}
USE_TZ = True
STATIC_URL = "/static/"
