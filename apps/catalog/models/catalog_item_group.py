from django.db import models

from common.models import BaseModel


class CatalogItemGroup(BaseModel):
    restaurant = models.ForeignKey(
        'restaurants.Restaurant',
        on_delete=models.CASCADE,
        related_name='catalog_item_groups',
    )
    category = models.ForeignKey(
        'catalog.CatalogCategory',
        on_delete=models.CASCADE,
        related_name='item_groups',
    )
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ('sort_order', 'name')
        constraints = [
            models.UniqueConstraint(
                fields=('restaurant', 'category', 'name'),
                name='catalog_item_group_unique_name_per_category',
            ),
        ]

    def __str__(self):
        return self.name


class CatalogItemGroupMember(BaseModel):
    group = models.ForeignKey(
        CatalogItemGroup,
        on_delete=models.CASCADE,
        related_name='members',
    )
    catalog_item = models.OneToOneField(
        'catalog.CatalogItem',
        on_delete=models.CASCADE,
        related_name='group_membership',
    )
    variant_name = models.CharField(max_length=100, blank=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ('sort_order', 'catalog_item__sort_order', 'catalog_item__name')
        constraints = [
            models.UniqueConstraint(
                fields=('group', 'sort_order'),
                name='catalog_item_group_unique_member_order',
            ),
        ]

    def __str__(self):
        return f'{self.group}: {self.variant_name or self.catalog_item.name}'
