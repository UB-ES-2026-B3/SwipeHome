"""Validación de US6; mantiene intactas las reglas históricas del registro."""
from django.contrib.auth.password_validation import CommonPasswordValidator
from django.core.exceptions import ValidationError

from .validation import validate_registration


def validate_profile_update(data):
    if not isinstance(data, dict):
        return None, {"body": "Debe ser un objeto JSON."}
    if not data or set(data) - {"name", "email"}:
        return None, {"body": "Envía name o email; no se permiten otros campos."}
    # Reutiliza exactamente las reglas vigentes, sin guardar campos artificiales.
    values, errors = validate_registration({
        "name": "Nombre válido", "email": "valid@example.com",
        "password": "contraseña válida de prueba", "role": "BUYER", **data,
    })
    return ({key: values[key] for key in data} if not errors else None), errors


def validate_password_change(data):
    if not isinstance(data, dict) or set(data) != {"current_password", "new_password"}:
        return {"body": "Se requieren exclusivamente current_password y new_password."}
    errors = {}
    current, new = data["current_password"], data["new_password"]
    if not isinstance(current, str) or not 1 <= len(current) <= 128:
        errors["current_password"] = "Introduce la contraseña actual (1–128 caracteres)."
    # La nueva contraseña sigue las mismas reglas que el registro (US1).
    # No se modifica ningún carácter de la contraseña.
    if not isinstance(new, str) or not 8 <= len(new) <= 128:
        errors["new_password"] = "La nueva contraseña debe tener entre 8 y 128 caracteres."
    elif new == current:
        errors["new_password"] = "La nueva contraseña debe ser diferente de la actual."
    elif not any(char.isupper() for char in new):
        errors["new_password"] = "La nueva contraseña debe incluir al menos una mayúscula."
    elif not any(char.isdigit() for char in new):
        errors["new_password"] = "La nueva contraseña debe incluir al menos un número."
    elif not any(not char.isalnum() and not char.isspace() for char in new):
        errors["new_password"] = "La nueva contraseña debe incluir al menos un símbolo."
    if "new_password" not in errors:
        try:
            CommonPasswordValidator().validate(new)
        except ValidationError:
            errors["new_password"] = "Evita contraseñas comunes."
    return errors
