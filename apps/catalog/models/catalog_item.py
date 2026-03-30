from django.db import models

from common.models import BaseModel


class CatalogItem(BaseModel):
    class Kind(models.TextChoices):
        DISH = 'dish', 'Dish'
        DRINK = 'drink', 'Drink'
        SERVICE = 'service', 'Service'
        PENALTY = 'penalty', 'Penalty'

    restaurant = models.ForeignKey('organizations.Restaurant', on_delete=models.CASCADE, related_name='catalog_items')
    branch = models.ForeignKey('organizations.Branch', on_delete=models.CASCADE, related_name='catalog_items')
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
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.DISH)
    description = models.TextField(blank=True)
    sku = models.CharField(max_length=60, blank=True)
    price = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    is_stoplisted = models.BooleanField(default=False)

    class Meta:
        ordering = ('name',)

    def __str__(self):
        return self.name
