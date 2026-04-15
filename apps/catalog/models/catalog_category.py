from django.db import models

from common.models import BaseModel


class CatalogCategory(BaseModel):
    class ImageSource(models.TextChoices):
        MXIK_CACHE = 'mxik-cache', 'MXIK cache'
        MANUAL = 'manual', 'Manual'

    restaurant = models.ForeignKey(
        'restaurants.Restaurant',
        on_delete=models.CASCADE,
        related_name='catalog_categories',
    )
    name = models.CharField(max_length=255)
    mxik_code = models.CharField(max_length=17, blank=True, db_index=True)
    mxik_name = models.CharField(max_length=512, blank=True)
    mxik_payload = models.JSONField(default=dict, blank=True)
    image_url = models.URLField(blank=True, null=True)
    image_source = models.CharField(max_length=32, blank=True, choices=ImageSource.choices)
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ('sort_order', 'name')

    def __str__(self):
        return self.name
