import importlib.util
import os
from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase

SETTINGS_FILE = Path(__file__).resolve().parents[1] / "config/settings.py"


def load_settings(**env):
    """Ejecuta settings.py con las variables de entorno indicadas."""
    base = {key: value for key, value in os.environ.items()
            if key not in ("DJANGO_DEV", "RENDER_EXTERNAL_HOSTNAME", "ALLOWED_HOSTS")}
    with patch.dict(os.environ, {**base, **env}, clear=True):
        spec = importlib.util.spec_from_file_location("settings_under_test", SETTINGS_FILE)
        config = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(config)
    return config


class DevelopmentSettingsTests(SimpleTestCase):
    def test_dev_flag_controls_debug(self):
        for value, dev in (("1", True), (" 1 ", True), ("", False), ("0", False)):
            with self.subTest(value=value):
                self.assertEqual(load_settings(DJANGO_DEV=value).DEBUG, dev)

    def test_no_database_sessions_or_csrf(self):
        config = load_settings()
        self.assertEqual(config.DATABASES, {})
        self.assertEqual(config.INSTALLED_APPS, ["accounts"])
        for removed in ("SessionMiddleware", "CsrfViewMiddleware", "AuthenticationMiddleware"):
            self.assertFalse(any(removed in middleware for middleware in config.MIDDLEWARE))
        for setting in ("AUTH_USER_MODEL", "PASSWORD_HASHERS", "CSRF_TRUSTED_ORIGINS", "SESSION_ENGINE"):
            self.assertFalse(hasattr(config, setting), setting)


class RenderSettingsTests(SimpleTestCase):
    """El bloque de Render es imprescindible en producción: estos tests lo protegen."""

    def test_render_host_is_allowed_and_proxy_https_is_trusted(self):
        config = load_settings(RENDER_EXTERNAL_HOSTNAME="swipehome.onrender.com")
        self.assertIn("swipehome.onrender.com", config.ALLOWED_HOSTS)
        self.assertEqual(config.SECURE_PROXY_SSL_HEADER, ("HTTP_X_FORWARDED_PROTO", "https"))

    def test_local_has_no_proxy_header(self):
        config = load_settings()
        self.assertEqual(config.ALLOWED_HOSTS, ["localhost", "127.0.0.1", "testserver"])
        self.assertFalse(hasattr(config, "SECURE_PROXY_SSL_HEADER"))

    def test_extra_allowed_hosts_from_env(self):
        config = load_settings(ALLOWED_HOSTS=" a.example.com, ,b.example.com ")
        self.assertEqual(config.ALLOWED_HOSTS[-2:], ["a.example.com", "b.example.com"])
