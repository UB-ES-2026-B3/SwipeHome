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
# DJANGO_BEHIND_TLS_PROXY=1 hace lo mismo en cualquier otro host cuyo proxy
# termine el TLS y envie X-Forwarded-Proto (p. ej. Azure Container Apps).
# Solo debe activarse detras de un proxy asi: si no, el cliente podria
# falsificar la cabecera.
_BEHIND_TLS_PROXY = os.environ.get("DJANGO_BEHIND_TLS_PROXY", "").strip() == "1"
if _RENDER_HOST or _BEHIND_TLS_PROXY:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

INSTALLED_APPS = ["corsheaders", "accounts"]
MIDDLEWARE = [
    # CorsMiddleware va lo mas arriba posible: debe responder a los preflight
    # OPTIONS y anadir las cabeceras CORS antes que CommonMiddleware.
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.common.CommonMiddleware",
]

# Origenes del frontend que pueden llamar a la API desde otro dominio,
# separados por comas (p. ej. el de Azure Static Web Apps). Vacio en local y
# en Render: alli el frontend usa rutas relativas (proxy de Vite / rewrite) y
# no hay peticiones entre origenes.
CORS_ALLOWED_ORIGINS = [
    o.strip() for o in os.environ.get("CORS_ALLOWED_ORIGINS", "").split(",") if o.strip()
]
# La API se autentica con Authorization: Bearer, sin cookies: no se envian
# credenciales entre origenes. Las cabeceras por defecto de django-cors-headers
# ya incluyen authorization y content-type.
CORS_ALLOW_CREDENTIALS = False
ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
# Sin modelos ni sesiones, Django no necesita base de datos: los usuarios viven en
# Firebase Auth y los perfiles en Firestore (accounts/repository.py).
DATABASES = {}
USE_TZ = True
STATIC_URL = "/static/"

# Sin esto solo se imprimen los WARNING o superiores: los INFO de authentication.py
# (token ausente o caducado) no saldrían ni en local ni en los logs de Render.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"simple": {"format": "%(levelname)s %(name)s: %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "simple"}},
    "loggers": {"accounts": {"handlers": ["console"], "level": "INFO", "propagate": False}},
}
