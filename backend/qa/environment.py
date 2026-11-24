import os
from contextlib import ExitStack
from uuid import uuid4

import requests
from firebase_admin import auth, credentials, delete_app, firestore, initialize_app
from google.auth.credentials import AnonymousCredentials

PROJECT = "demo-swipehome-us4"
HOST = "127.0.0.1"
AUTH_HOST = f"{HOST}:9099"
FIRESTORE_HOST = f"{HOST}:8080"
BLOB_ENDPOINT = f"http://{HOST}:10000/devstoreaccount1"
# Clave pública del emulador Azurite.
BLOB_CONNECTION = (
    "DefaultEndpointsProtocol=http;AccountName=devstoreaccount1;"
    "AccountKey=Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/"
    "K1SZFPTOtr/KBHBeksoGMGw==;"
    f"BlobEndpoint={BLOB_ENDPOINT};"
)
PROJECT_KEYS = ("GCLOUD_PROJECT", "GOOGLE_CLOUD_PROJECT", "FIREBASE_PROJECT_ID")
CREDENTIAL_KEYS = (
    "FIREBASE_TOKEN", "FIREBASE_SERVICE_ACCOUNT_JSON", "GOOGLE_APPLICATION_CREDENTIALS",
    "GOOGLE_OAUTH_ACCESS_TOKEN", "CLOUDSDK_AUTH_ACCESS_TOKEN",
)
LOCAL_ENV = {
    "FIREBASE_AUTH_EMULATOR_HOST": AUTH_HOST,
    "FIRESTORE_EMULATOR_HOST": FIRESTORE_HOST,
    "FIREBASE_CONFIG": '{"projectId":"demo-swipehome-us4"}',
    "AZURE_STORAGE_CONNECTION_STRING": BLOB_CONNECTION,
    "AZURE_STORAGE_CONTAINER": "listings",
    "NO_PROXY": HOST,
    **dict.fromkeys(PROJECT_KEYS, PROJECT),
}


class LocalCredential(credentials.Base):
    def get_credential(self):
        return AnonymousCredentials()


def configure():
    for name in tuple(os.environ):
        if name.upper() in (*CREDENTIAL_KEYS, "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "GRPC_PROXY") or name.upper().startswith("VITE_"):
            del os.environ[name]
    os.environ.update(LOCAL_ENV)


def require_firebase():
    if os.environ.get("FIREBASE_AUTH_EMULATOR_HOST") != AUTH_HOST:
        raise RuntimeError("QA requiere Firebase Auth Emulator en 127.0.0.1:9099.")
    if os.environ.get("FIRESTORE_EMULATOR_HOST") != FIRESTORE_HOST:
        raise RuntimeError("QA requiere Firestore Emulator en 127.0.0.1:8080.")
    if os.environ.get("GCLOUD_PROJECT") != PROJECT or any(
        os.environ.get(key, PROJECT) != PROJECT for key in PROJECT_KEYS
    ):
        raise RuntimeError("QA requiere el proyecto demo-swipehome-us4.")
    if any(os.environ.get(key) for key in CREDENTIAL_KEYS):
        raise RuntimeError("Retira las credenciales de producción del proceso de QA.")


def new_firebase():
    require_firebase()
    app = initialize_app(LocalCredential(), {"projectId": PROJECT, "httpTimeout": 8}, name=f"qa-{uuid4().hex}")
    try:
        db = firestore.client(app=app)
        if not auth.Client(app).emulated or db.project != PROJECT or db._emulator_host != FIRESTORE_HOST:
            raise RuntimeError("El SDK de Firebase no seleccionó los emuladores de QA.")
        return app, db
    except Exception:
        delete_app(app)
        raise


def blob_container():
    from accounts.azure_storage import get_container_client

    if os.environ.get("AZURE_STORAGE_CONNECTION_STRING") != BLOB_CONNECTION:
        raise RuntimeError("QA requiere exclusivamente la conexión de desarrollo a Azurite.")
    container = get_container_client()
    if container.url.rstrip("/") != f"{BLOB_ENDPOINT}/listings":
        raise RuntimeError("El cliente de almacenamiento del backend no usa Azurite listings.")
    return container


def check_auth_service():
    with requests.Session() as session:
        session.trust_env = False
        response = session.get(f"http://{AUTH_HOST}/emulator/v1/projects/{PROJECT}/config", timeout=4)
        response.raise_for_status()
        if "signIn" not in response.json():
            raise RuntimeError("El puerto 9099 no ofrece la API de configuración del Auth Emulator.")


def verify_services(*, create_container=False):
    require_firebase()
    check_auth_service()
    uid = f"qa-probe-{uuid4().hex}"
    with ExitStack() as cleanup:
        app, db = new_firebase()
        cleanup.callback(delete_app, app)
        cleanup.callback(db.close)
        reference = db.collection("qa_connectivity").document(uid)
        if reference.get(retry=None, timeout=5).exists:
            raise RuntimeError("El identificador de la sonda de Firestore ya existe.")
        container = blob_container()
        if not container.exists():
            if not create_container:
                raise RuntimeError("Falta el contenedor listings en la instancia de Azurite abierta.")
            container.create_container(public_access="blob")
        blob = container.get_blob_client(f"{uid}/probe.txt")
        if blob.exists():
            raise RuntimeError("El identificador de la sonda de Azurite ya existe.")

        # Las escrituras temporales empiezan después de comprobar los tres clientes.
        account = auth.create_user(uid=uid, email=f"{uid}@example.com", app=app)
        cleanup.callback(auth.delete_user, account.uid, app=app)
        reference.create({"probe": uid}, retry=None, timeout=5)
        cleanup.callback(reference.delete, retry=None, timeout=5)
        blob.upload_blob(b"swipehome-qa", overwrite=False)
        cleanup.callback(blob.delete_blob)
        if (auth.get_user(uid, app=app).uid != uid or reference.get(timeout=5).get("probe") != uid
                or blob.download_blob().readall() != b"swipehome-qa"):
            raise RuntimeError("La lectura de una sonda de QA no coincide con la escritura.")
    with ExitStack() as cleanup:
        app, db = new_firebase()
        cleanup.callback(delete_app, app)
        cleanup.callback(db.close)
        try:
            auth.get_user(uid, app=app)
        except auth.UserNotFoundError:
            pass
        else:
            raise RuntimeError("La sonda de Auth sigue existiendo tras la limpieza.")
        if db.collection("qa_connectivity").document(uid).get(timeout=5).exists or blob.exists():
            raise RuntimeError("Quedaron sondas de conectividad tras la limpieza.")
    print("PASS CON EMULADORES: Auth 9099, Firestore 8080, Azurite 10000/listings. Sondas creadas, leídas y eliminadas.", flush=True)
