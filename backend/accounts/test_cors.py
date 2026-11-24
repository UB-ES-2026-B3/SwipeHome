from django.test import SimpleTestCase, override_settings

from .test_development import load_settings

SWA_ORIGIN = "https://swipehome.azurestaticapps.net"
OTHER_ORIGIN = "https://evil.example.com"


def preflight(client, origin):
    """Preflight como el que envía el navegador antes de un GET con Bearer."""
    return client.options(
        "/api/health",
        HTTP_ORIGIN=origin,
        HTTP_ACCESS_CONTROL_REQUEST_METHOD="GET",
        HTTP_ACCESS_CONTROL_REQUEST_HEADERS="authorization",
    )


class CorsPreflightTests(SimpleTestCase):
    """El frontend de Azure Static Web Apps llama a la API desde otro origen."""

    @override_settings(CORS_ALLOWED_ORIGINS=[SWA_ORIGIN])
    def test_allowed_origin_is_echoed_and_authorization_is_allowed(self):
        response = preflight(self.client, SWA_ORIGIN)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Access-Control-Allow-Origin"], SWA_ORIGIN)
        allowed = [h.strip().lower() for h in response["Access-Control-Allow-Headers"].split(",")]
        self.assertIn("authorization", allowed)
        # Bearer, sin cookies: nunca se anuncian credenciales entre orígenes.
        self.assertNotIn("Access-Control-Allow-Credentials", response)

    @override_settings(CORS_ALLOWED_ORIGINS=[SWA_ORIGIN])
    def test_other_origin_gets_no_cors_header(self):
        response = preflight(self.client, OTHER_ORIGIN)

        self.assertNotIn("Access-Control-Allow-Origin", response)

    @override_settings(CORS_ALLOWED_ORIGINS=[])
    def test_empty_setting_allows_no_origin(self):
        response = preflight(self.client, SWA_ORIGIN)

        self.assertNotIn("Access-Control-Allow-Origin", response)

    @override_settings(CORS_ALLOWED_ORIGINS=[SWA_ORIGIN])
    def test_actual_request_keeps_its_response(self):
        response = self.client.get("/api/health", HTTP_ORIGIN=SWA_ORIGIN)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})
        self.assertEqual(response["Access-Control-Allow-Origin"], SWA_ORIGIN)


class CorsSettingsTests(SimpleTestCase):
    def test_origins_are_read_from_env(self):
        config = load_settings(CORS_ALLOWED_ORIGINS=f" {SWA_ORIGIN}, ,http://localhost:5173 ")
        self.assertEqual(config.CORS_ALLOWED_ORIGINS, [SWA_ORIGIN, "http://localhost:5173"])
        self.assertFalse(config.CORS_ALLOW_CREDENTIALS)

    def test_empty_env_means_no_origins(self):
        for value in ("", " , "):
            with self.subTest(value=value):
                self.assertEqual(load_settings(CORS_ALLOWED_ORIGINS=value).CORS_ALLOWED_ORIGINS, [])

    def test_cors_middleware_runs_before_common_middleware(self):
        middleware = load_settings().MIDDLEWARE
        self.assertEqual(middleware[0], "corsheaders.middleware.CorsMiddleware")
        self.assertLess(
            middleware.index("corsheaders.middleware.CorsMiddleware"),
            middleware.index("django.middleware.common.CommonMiddleware"),
        )
