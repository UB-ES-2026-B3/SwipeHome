import json
import logging

from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_POST

from .models import User
from .validation import validate_registration

logger = logging.getLogger(__name__)


def internal_error():
    # Never log the exception or payload: either may contain credentials/SQL.
    logger.error("No se pudo completar el registro.")
    return JsonResponse({"error": "No se pudo completar el registro. Inténtalo de nuevo."}, status=500)


@sensitive_post_parameters("password")
@csrf_exempt
@require_POST
def register(request):
    # This endpoint creates accounts only; session creation belongs to US1.4A.
    if request.content_type != "application/json":
        return JsonResponse({"error": "Se requiere application/json."}, status=400)
    try:
        data = json.loads(request.body)
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({"error": "JSON inválido."}, status=400)
    values, errors = validate_registration(data)
    if errors:
        return JsonResponse({"errors": errors}, status=400)
    try:
        # Hash outside the write transaction to keep the SQLite lock short.
        user = User(name=values["name"], email=values["email"], role=values["role"])
        user.set_password(values["password"])
        with transaction.atomic():
            user.save(force_insert=True)
            response = JsonResponse(
                {"id": user.pk, "name": user.name, "email": user.email, "role": user.role},
                status=201,
            )
        return response
    except IntegrityError:
        # Query only after rollback; other integrity failures are internal errors.
        try:
            if User.objects.filter(email=values["email"]).exists():
                return JsonResponse({"error": "El email ya está registrado."}, status=409)
        except Exception:
            return internal_error()
        return internal_error()
    except Exception:
        return internal_error()
