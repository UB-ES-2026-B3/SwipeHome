from django.apps import AppConfig
from django.db.backends.signals import connection_created

from .fields import normalize_account_email


def register_sqlite_email_normalization(sender, connection, **kwargs):
    if connection.vendor == "sqlite":
        # SQLite LOWER/TRIM do not match Python's Unicode normalization rules.
        connection.connection.create_function(
            "swipehome_normalize_email", 1, normalize_account_email, deterministic=True
        )


class AccountsConfig(AppConfig):
    name = "accounts"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        connection_created.connect(
            register_sqlite_email_normalization,
            dispatch_uid="accounts.sqlite_email_normalization",
            weak=False,
        )
