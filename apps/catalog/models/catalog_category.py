from django.db import models

from common.models import BaseModel


class CatalogCategory(BaseModel):
    class Kind(models.TextChoices):
        DISH = 'dish', 'Dish'
        DRINK = 'drink', 'Drink'
        SERVICE = 'service', 'Service'
        PENALTY = 'penalty', 'Penalty'

    restaurant = models.ForeignKey(
        'organizations.Restaurant',
        on_delete=models.CASCADE,
        related_name='catalog_categories',
    )
    branch = models.ForeignKey('organizations.Branch', on_delete=models.CASCADE, related_name='catalog_categories')
    name = models.CharField(max_length=255)
    mxik_code = models.CharField(max_length=17, blank=True, db_index=True)
    mxik_name = models.CharField(max_length=512, blank=True)
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.DISH)
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ('sort_order', 'name')

    def __str__(self):
        return self.name
