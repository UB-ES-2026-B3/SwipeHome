# check=skip=JSONArgsRecommended
# Imagen del backend para Azure Container Apps. Se construye en la nube con
# `az acr build` (contexto = backend/) o en local con `docker build backend`.
# Sin secretos: todas las variables (DJANGO_SECRET_KEY, Firebase, Azure Blob,
# ALLOWED_HOSTS, CORS...) se inyectan al ejecutar el contenedor.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Primero solo las dependencias: esta capa se reutiliza mientras
# requirements.txt no cambie.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Usuario sin privilegios. El código queda en propiedad de root: el proceso
# puede leerlo pero no modificarlo.
RUN useradd --system --uid 10001 --user-group --create-home app

COPY . .

USER app

EXPOSE 8000

# Forma shell para que ${PORT:-8000} se expanda; `exec` deja a gunicorn como
# PID 1 y recibe directamente el SIGTERM al parar el contenedor (por eso se
# omite el aviso JSONArgsRecommended en la primera línea).
# --timeout 30: los reintentos y timeouts de Azure Blob (azure_storage.py)
# están calculados para caber dentro; no subirlo sin revisarlos.
CMD exec gunicorn config.wsgi:application --bind 0.0.0.0:${PORT:-8000} --workers 2 --threads 4 --timeout 30 --access-logfile -
