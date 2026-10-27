"""Validación de US6; mantiene intactas las reglas históricas del registro."""
from django.contrib.auth.password_validation import CommonPasswordValidator, NumericPasswordValidator
from django.core.exceptions import ValidationError
from django.core.validators import validate_email

from .fields import normalize_account_email


def validate_profile_update(data):
    if not isinstance(data, dict):
        return None, {"body": "Debe ser un objeto JSON."}
    if not data or set(data) - {"name", "email"}:
        return None, {"body": "Envía name o email; no se permiten otros campos."}
    values, errors = {}, {}
    if "name" in data:
        if not isinstance(data["name"], str):
            errors["name"] = "El nombre debe ser texto."
        else:
            name = data["name"].strip()
            if not 2 <= len(name) <= 80:
                errors["name"] = "El nombre debe tener entre 2 y 80 caracteres."
            else:
                values["name"] = name
    if "email" in data:
        if not isinstance(data["email"], str):
            errors["email"] = "El email debe ser texto."
        else:
            email = normalize_account_email(data["email"])
            try:
                validate_email(email)
            except ValidationError:
                errors["email"] = "Introduce un email válido."
            if len(email) > 254 or any(char.isspace() for char in email):
                errors["email"] = "Introduce un email válido."
            else:
                values["email"] = email
    return (values if not errors else None), errors


def validate_password_change(data):
    if not isinstance(data, dict) or set(data) != {"current_password", "new_password"}:
        return {"body": "Se requieren exclusivamente current_password y new_password."}
    errors = {}
    current, new = data["current_password"], data["new_password"]
    if not isinstance(current, str) or not 1 <= len(current) <= 128:
        errors["current_password"] = "Introduce la contraseña actual (1–128 caracteres)."
    # Política US6: longitud, contenido no vacío y distinta de la actual.
    # No se modifica ningún carácter de la contraseña.
    if not isinstance(new, str) or not 15 <= len(new) <= 128 or not new.strip():
        errors["new_password"] = "La nueva contraseña debe tener entre 15 y 128 caracteres y no ser solo espacios."
    elif new == current:
        errors["new_password"] = "La nueva contraseña debe ser diferente de la actual."
    if "new_password" not in errors:
        try:
            CommonPasswordValidator().validate(new)
            NumericPasswordValidator().validate(new)
        except ValidationError:
            errors["new_password"] = "Evita contraseñas comunes o formadas únicamente por números."
    return errors
