import importlib.util
import io
import os
from pathlib import Path
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase, SimpleTestCase

from .models import User

VALID = {
    "name": "Ana García",
    "email": "ana@example.com",
    "password": "  contraseña íntegra 🙂  ",
    "role": "BUYER",
}


class DevelopmentSettingsTests(SimpleTestCase):
    def test_dev_flag_and_secure_defaults(self):
        for value, dev in (("1", True), (" 1 ", True), ("", False), ("0", False)):
            with self.subTest(value=value), patch.dict(os.environ, {"DJANGO_DEV": value}):
                spec = importlib.util.spec_from_file_location(
                    "development_settings_test", Path(__file__).resolve().parents[1] / "config/settings.py"
                )
                config = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(config)
                try:
                    self.assertEqual(config.DEBUG, dev)
                    self.assertEqual(config.SESSION_COOKIE_SECURE, not dev)
                    self.assertFalse(hasattr(config, "CSRF_TRUSTED_ORIGINS"))
                finally:
                    config.TEST_DATABASE_DIR.cleanup()


class SuperuserTests(TestCase):
    def test_management_command_creates_authenticatable_superuser(self):
        with patch.dict(os.environ, {"DJANGO_SUPERUSER_PASSWORD": VALID["password"]}):
            call_command(
                "createsuperuser", interactive=False, email="ADMIN@EXAMPLE.COM",
                name="Admin", role="SELLER", stdout=io.StringIO(),
            )
        user = User.objects.get(email="admin@example.com")
        self.assertTrue(user.is_staff)
        self.assertTrue(user.is_superuser)
        self.assertTrue(user.check_password(VALID["password"]))
        self.assertTrue(user.has_perm("accounts.change_user"))
        self.assertTrue(self.client.login(email=user.email, password=VALID["password"]))

    def test_regular_users_have_no_admin_permissions(self):
        user = User.objects.create_user(**VALID)
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertFalse(user.has_perm("accounts.change_user"))

    def test_rejects_invalid_superuser_flags_and_role(self):
        for flags in ({"is_staff": False}, {"is_superuser": False}, {"role": "ADMIN"}):
            with self.subTest(flags=flags), self.assertRaises(ValueError):
                User.objects.create_superuser(**{**VALID, **flags})
        self.assertEqual(User.objects.count(), 0)
