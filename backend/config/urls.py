from django.urls import path
from accounts.views import current_user, login_view, register
from config.health import health

urlpatterns = [
    path("api/health", health, name="health"),
    path("api/auth/register", register, name="register"),
    path("api/auth/login", login_view, name="login"),
    path("api/auth/me", current_user, name="current-user"),
]
