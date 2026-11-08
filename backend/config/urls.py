from django.urls import path
from accounts.views import current_user, register
from accounts.profile_views import logout, password, update_profile
from accounts.notification_views import notifications
from config.health import health
from properties.views import create_property, decide_property, explore_properties


def profile_dispatch(request):
    if request.method in ("PATCH", "PUT"):
        return update_profile(request)
    return current_user(request)


urlpatterns = [
    path("api/notificaciones", notifications, name="notifications"),
    path("api/health", health, name="health"),
    path("api/auth/register", register, name="register"),
    path("api/auth/me", profile_dispatch, name="current-user"),
    path("api/auth/me/password", password, name="change-password"),
    path("api/auth/logout", logout, name="logout"),
    path("api/inmuebles", create_property, name="properties"),
    path("api/inmuebles/explorar", explore_properties, name="explore-properties"),
    path("api/inmuebles/decidir", decide_property, name="decide-property"),
]
