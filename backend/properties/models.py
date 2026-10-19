from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models


class Property(models.Model):
    title = models.CharField(max_length=255)
    street = models.CharField(max_length=255)
    city = models.CharField(max_length=255)
    postal_code = models.CharField(max_length=255)
    description = models.TextField()
    price = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(0)])
    surface = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(0)])
    bedrooms = models.PositiveIntegerField()
    bathrooms = models.PositiveIntegerField()
    people = models.PositiveIntegerField()
    shared_accommodation = models.BooleanField()
    seller = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="properties",
    )
    published = models.BooleanField(default=False)
    published_at = models.DateTimeField(null=True, blank=True)


class PropertyPhoto(models.Model):
    property = models.ForeignKey(
        Property,
        on_delete=models.CASCADE,
        related_name="photos",
    )
    file = models.FileField(upload_to="properties/")
    position = models.PositiveIntegerField()

    class Meta:
        ordering = ["position"]
        constraints = [
            models.UniqueConstraint(
                fields=["property", "position"],
                name="properties_photo_unique_position",
            ),
        ]
