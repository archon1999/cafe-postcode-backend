from django.db import models

from common.models import BaseModel


class CatalogItem(BaseModel):
    restaurant = models.ForeignKey('organizations.Restaurant', on_delete=models.CASCADE, related_name='catalog_items')
    category = models.ForeignKey(
        'catalog.CatalogCategory',
        on_delete=models.SET_NULL,
        related_name='items',
        null=True,
        blank=True,
    )
    prep_station = models.ForeignKey(
        'organizations.PrepStation',
        on_delete=models.SET_NULL,
        related_name='catalog_items',
        null=True,
        blank=True,
    )
    name = models.CharField(max_length=255)
    mxik_code = models.CharField(max_length=17, blank=True, db_index=True)
    mxik_name = models.CharField(max_length=512, blank=True)
    description = models.TextField(blank=True)
    price = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    is_stoplisted = models.BooleanField(default=False)

    class Meta:
        ordering = ('name',)

    def __str__(self):
        return self.name
