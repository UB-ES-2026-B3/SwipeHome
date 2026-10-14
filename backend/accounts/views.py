import json
import logging
from sqlite3 import IntegrityError as SQLiteIntegrityError, SQLITE_CONSTRAINT_UNIQUE

from django.contrib.auth import login
from django.contrib.sessions.middleware import SessionMiddleware
from django.middleware.csrf import get_token
from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods

from .models import User
from .validation import validate_registration

logger = logging.getLogger(__name__)


def internal_error():
    # Never log the exception or payload: either may contain credentials/SQL.
    logger.error("No se pudo completar el registro.")
    return JsonResponse({"error": "No se pudo completar el registro. Inténtalo de nuevo."}, status=500)


@sensitive_post_parameters("password")
@require_http_methods(["GET", "POST"])
def register(request):
    if request.method == "GET":
        response = JsonResponse({"csrfToken": get_token(request)})
        response["Cache-Control"] = "no-store"
        return response
    if request.content_type != "application/json":
        return JsonResponse({"error": "Se requiere application/json."}, status=400)
    try:
        data = json.loads(request.body)
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({"error": "JSON inválido."}, status=400)
    values, errors = validate_registration(data)
    if errors:
        return JsonResponse({"errors": errors}, status=400)
    original_session = request.session
    original_user = request.user
    completed = False
    try:
        # Hash outside the write transaction to keep the SQLite lock short.
        user = User(name=values["name"], email=values["email"], role=values["role"])
        user.set_password(values["password"])
        with transaction.atomic():
            user.save(force_insert=True)
            # Work on a separate store so rollback also restores request state.
            request.session = type(original_session)(original_session.session_key)
            login(request, user)

            response = JsonResponse(
                {"id": user.pk, "name": user.name, "email": user.email, "role": user.role},
                status=201,
            )
            # Run Django's persistence and cookie handling BEFORE committing.
            # The outer middleware must not perform a second, non-atomic save.
            response = SessionMiddleware(lambda request: response).process_response(request, response)
            request.session.modified = False
        completed = True
        return response
    except IntegrityError as error:
        # SQLite is the established local backend. Match the actual violated
        # constraint, not the mere existence of an account after rollback.
        cause = error.__cause__
        if (
            isinstance(cause, SQLiteIntegrityError)
            and getattr(cause, "sqlite_errorcode", None) == SQLITE_CONSTRAINT_UNIQUE
            and str(cause) == "UNIQUE constraint failed: accounts_user.email"
        ):
            return JsonResponse({"error": "El email ya est\u00e1 registrado."}, status=409)
        return internal_error()
    except Exception:
        return internal_error()

    finally:
        if not completed:
            request.session = original_session
            request.user = original_user


def csrf_failure(request, reason=""):
    return JsonResponse({"error": "Verificacion CSRF rechazada."}, status=403)
