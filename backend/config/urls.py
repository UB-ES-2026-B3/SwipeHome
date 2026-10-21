from django.urls import path
from accounts.views import current_user, register
from config.health import health
from properties.views import create_property

urlpatterns = [
    path("api/health", health, name="health"),
    path("api/auth/register", register, name="register"),
    path("api/auth/me", current_user, name="current-user"),
    path("api/inmuebles", create_property, name="create-property"),
]
