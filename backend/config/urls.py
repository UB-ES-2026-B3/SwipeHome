from django.urls import path
from accounts.views import current_user, login_view, register
from properties.views import create_property

urlpatterns = [
    path("api/auth/register", register, name="register"),
    path("api/auth/login", login_view, name="login"),
    path("api/auth/me", current_user, name="current-user"),
    path("api/inmuebles", create_property, name="create-property"),
]
