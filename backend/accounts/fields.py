from django.db import models


def normalize_account_email(email):
    """Canonical account identity, including the entire address and whitespace."""
    return email.strip().lower() if isinstance(email, str) else email


class NormalizedEmailField(models.EmailField):
    """Normalize ORM inserts, literal updates and lookups before database use."""

    def get_prep_value(self, value):
        return normalize_account_email(super().get_prep_value(value))

    def pre_save(self, model_instance, add):
        value = self.get_prep_value(super().pre_save(model_instance, add))
        setattr(model_instance, self.attname, value)
        return value
