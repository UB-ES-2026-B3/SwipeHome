from django.urls import path
from accounts.views import current_user, register
from accounts.profile_views import logout, password, update_profile
from config.health import health
from properties.views import create_property


def profile_dispatch(request):
    if request.method in ("PATCH", "PUT"):
        return update_profile(request)
    return current_user(request)


urlpatterns = [
    path("api/health", health, name="health"),
    path("api/auth/register", register, name="register"),
    path("api/auth/me", profile_dispatch, name="current-user"),
    path("api/auth/me/password", password, name="change-password"),
    path("api/auth/logout", logout, name="logout"),
    path("api/inmuebles", create_property, name="create-property"),
]
