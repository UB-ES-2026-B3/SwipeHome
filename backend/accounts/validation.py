from django.core.exceptions import ValidationError
from django.core.validators import validate_email


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
    email = data["email"].strip().lower()
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
    if not 15 <= len(password) <= 128:
        errors["password"] = "La contraseña debe tener entre 15 y 128 caracteres."
    if role not in ("SELLER", "BUYER"):
        errors["role"] = "Selecciona SELLER o BUYER."
    return {"name": name, "email": email, "password": password, "role": role}, errors
