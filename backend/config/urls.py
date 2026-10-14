from django.urls import path
from accounts.views import register

urlpatterns = [path("api/auth/register", register, name="register")]
