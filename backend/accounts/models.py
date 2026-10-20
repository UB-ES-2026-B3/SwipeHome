from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.db import models

from .fields import NormalizedEmailField, normalize_account_email


class UserManager(BaseUserManager):
    @classmethod
    def normalize_email(cls, email):
        return normalize_account_email(email)

    def create_user(self, email, password, name, role, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        user = self.model(email=email, name=name, role=role, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password, name, role, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        if extra_fields.get("is_staff") is not True:
            raise ValueError("Un superusuario debe tener is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Un superusuario debe tener is_superuser=True.")
        if role not in ("BUYER", "SELLER"):
            raise ValueError("El rol debe ser BUYER o SELLER.")
        return self.create_user(email, password, name, role, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    name = models.CharField(max_length=80)
    email = NormalizedEmailField(max_length=254, unique=True)
    role = models.CharField(max_length=6, choices=[("SELLER", "SELLER"), ("BUYER", "BUYER")])
    is_staff = models.BooleanField(default=False)
    objects = UserManager()
    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["name", "role"]

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(email=models.Func(models.F("email"), function="swipehome_normalize_email")),
                name="accounts_user_normalized_email",
            ),
            models.CheckConstraint(
                condition=models.Q(role__in=["SELLER", "BUYER"]),
                name="accounts_user_valid_role",
            )
        ]
