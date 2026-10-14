from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.db import models


class UserManager(BaseUserManager):
    def create_user(self, email, password, name, role):
        user = self.model(email=email.strip().lower(), name=name, role=role)
        user.set_password(password)
        user.save(using=self._db)
        return user


class User(AbstractBaseUser):
    name = models.CharField(max_length=80)
    email = models.EmailField(max_length=254, unique=True)
    role = models.CharField(max_length=6, choices=[("SELLER", "SELLER"), ("BUYER", "BUYER")])
    objects = UserManager()
    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["name", "role"]

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(role__in=["SELLER", "BUYER"]),
                name="accounts_user_valid_role",
            )
        ]
