from django.core.exceptions import ValidationError
from django.db import models

from common.models import BaseModel


class ModifierGroup(BaseModel):
    class SelectionType(models.TextChoices):
        SINGLE = 'single', 'Single choice'
        MULTIPLE = 'multiple', 'Multiple choice'

    restaurant = models.ForeignKey(
        'restaurants.Restaurant',
        on_delete=models.CASCADE,
        related_name='modifier_groups',
    )
    name = models.CharField(max_length=255)
    selection_type = models.CharField(
        max_length=16,
        choices=SelectionType.choices,
        default=SelectionType.SINGLE,
    )
    min_selections = models.PositiveSmallIntegerField(default=0)
    max_selections = models.PositiveSmallIntegerField(default=1)
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ('sort_order', 'name')
        constraints = [
            models.UniqueConstraint(fields=('restaurant', 'name'), name='modifier_group_unique_restaurant_name'),
        ]

    def clean(self):
        super().clean()
        if self.max_selections < 1:
            raise ValidationError({'max_selections': 'At least one selection must be allowed.'})
        if self.min_selections > self.max_selections:
            raise ValidationError({'min_selections': 'Minimum selections cannot exceed maximum selections.'})
        if self.selection_type == self.SelectionType.SINGLE and self.max_selections != 1:
            raise ValidationError({'max_selections': 'Single-choice groups must allow exactly one selection.'})

    def __str__(self):
        return self.name


class ModifierOption(BaseModel):
    group = models.ForeignKey(ModifierGroup, on_delete=models.CASCADE, related_name='options')
    name = models.CharField(max_length=255)
    price_delta = models.PositiveIntegerField(default=0)
    is_default = models.BooleanField(default=False)
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ('sort_order', 'name')
        constraints = [
            models.UniqueConstraint(fields=('group', 'name'), name='modifier_option_unique_group_name'),
        ]

    def __str__(self):
        return f'{self.group.name}: {self.name}'


class CatalogItemModifierGroup(BaseModel):
    catalog_item = models.ForeignKey(
        'catalog.CatalogItem',
        on_delete=models.CASCADE,
        related_name='modifier_assignments',
    )
    modifier_group = models.ForeignKey(
        ModifierGroup,
        on_delete=models.PROTECT,
        related_name='item_assignments',
    )
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ('sort_order', 'modifier_group__sort_order', 'modifier_group__name')
        constraints = [
            models.UniqueConstraint(
                fields=('catalog_item', 'modifier_group'),
                name='catalog_item_modifier_group_unique_assignment',
            ),
        ]

    def clean(self):
        super().clean()
        if (
            self.catalog_item_id
            and self.modifier_group_id
            and self.catalog_item.restaurant_id != self.modifier_group.restaurant_id
        ):
            raise ValidationError({'modifier_group': 'Modifier group must belong to the product restaurant.'})

    def __str__(self):
        return f'{self.catalog_item.name}: {self.modifier_group.name}'
