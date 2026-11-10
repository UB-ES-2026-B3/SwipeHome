"""Reautenticación con Firebase REST. Nunca devuelve su respuesta sin filtrar."""
import os

import requests
from firebase_admin import auth
from firebase_admin.exceptions import InvalidArgumentError

from .firebase import FirebaseConfigError, get_app


class IncorrectPassword(Exception):
    pass


class PasswordRejected(Exception):
    pass


def change_password(uid, current_password, new_password):
    key = os.environ.get("FIREBASE_WEB_API_KEY", "").strip()
    if not key:
        raise FirebaseConfigError("Falta FIREBASE_WEB_API_KEY.")
    user = auth.get_user(uid, app=get_app())
    response = requests.post(
        "https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword",
        params={"key": key},
        json={"email": user.email, "password": current_password, "returnSecureToken": True},
        timeout=(5, 15),
    )
    if response.status_code == 400:
        code = response.json().get("error", {}).get("message", "")
        if code in {"INVALID_LOGIN_CREDENTIALS", "INVALID_PASSWORD", "EMAIL_NOT_FOUND"}:
            raise IncorrectPassword() from None
    if response.status_code != 200:
        # Ni el mensaje de Google, ni su respuesta, ni credenciales llegan al cliente.
        raise RuntimeError("No se pudo reautenticar.")
    if response.json().get("localId") != uid:
        raise IncorrectPassword()
    # Se prepara antes de modificar la contraseña: un fallo de firma no la cambia.
    continuity = auth.create_custom_token(uid, app=get_app()).decode("ascii")
    try:
        auth.update_user(uid, password=new_password, app=get_app())
    except (ValueError, InvalidArgumentError):
        raise PasswordRejected() from None
    return continuity
