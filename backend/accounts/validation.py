from django.core.exceptions import ValidationError
from django.core.validators import validate_email

from .fields import normalize_account_email


def validate_registration(data):
    errors = {}
    if not isinstance(data, dict):
        return None, {"body": "Debe ser un objeto JSON."}
    for field in ("name", "email", "password", "role"):
        if field not in data or not isinstance(data[field], str):
            errors[field] = "Campo obligatorio de tipo texto."
    if errors:
        return None, errors

    name = data["name"].strip()
    email = normalize_account_email(data["email"])
    password = data["password"]
    role = data["role"]
    if not 2 <= len(name) <= 80:
        errors["name"] = "El nombre debe tener entre 2 y 80 caracteres."
    try:
        validate_email(email)
    except ValidationError:
        errors["email"] = "Introduce un email válido."
    if len(email) > 254 or any(char.isspace() for char in email):
        errors["email"] = "Introduce un email válido."
    if not 8 <= len(password) <= 128:
        errors["password"] = "La contraseña debe tener entre 8 y 128 caracteres."
    elif not any(char.isupper() for char in password):
        errors["password"] = "La contraseña debe incluir al menos una mayúscula."
    elif not any(char.isdigit() for char in password):
        errors["password"] = "La contraseña debe incluir al menos un número."
    elif not any(not char.isalnum() and not char.isspace() for char in password):
        errors["password"] = "La contraseña debe incluir al menos un símbolo."
    if role not in ("SELLER", "BUYER"):
        errors["role"] = "Selecciona SELLER o BUYER."
    return {"name": name, "email": email, "password": password, "role": role}, errors


def validate_login(data):
    errors = {}
    if not isinstance(data, dict):
        return None, {"body": "Debe ser un objeto JSON."}
    for field in ("email", "password"):
        if field not in data or not isinstance(data[field], str):
            errors[field] = "Campo obligatorio de tipo texto."
    if errors:
        return None, errors

    email = normalize_account_email(data["email"])
    password = data["password"]
    try:
        validate_email(email)
    except ValidationError:
        errors["email"] = "Introduce un email válido."
    if len(email) > 254 or any(char.isspace() for char in email):
        errors["email"] = "Introduce un email válido."
    if not 1 <= len(password) <= 128:
        errors["password"] = "La contraseña debe tener entre 1 y 128 caracteres."
    return {"email": email, "password": password}, errors
