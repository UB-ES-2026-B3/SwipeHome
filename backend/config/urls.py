from django.urls import path
from accounts.views import current_user, register
from config.health import health

urlpatterns = [
    path("api/health", health, name="health"),
    path("api/auth/register", register, name="register"),
    path("api/auth/me", current_user, name="current-user"),
]
