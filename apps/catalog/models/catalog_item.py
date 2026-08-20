from pathlib import Path
import uuid

from django.db import models

from common.models import BaseModel
from common.storages import CatalogItemImageStorage


def catalog_item_image_upload_to(instance, filename: str) -> str:
    suffix = Path(filename or '').suffix.lower() or '.bin'
    restaurant_id = instance.restaurant_id or 'unassigned'
    return f'{restaurant_id}/{uuid.uuid4().hex}{suffix}'


class CatalogItem(BaseModel):
    class ItemType(models.TextChoices):
        PRODUCT = 'product', 'Product'
        SERVICE = 'service', 'Service'

    class SaleUnit(models.TextChoices):
        PIECE = 'piece', 'Piece'
        KILOGRAM = 'kg', 'Kilogram'

    class ImageSource(models.TextChoices):
        MXIK_CACHE = 'mxik-cache', 'MXIK cache'
        MANUAL = 'manual', 'Manual'

    restaurant = models.ForeignKey('restaurants.Restaurant', on_delete=models.CASCADE, related_name='catalog_items')
    category = models.ForeignKey(
        'catalog.CatalogCategory',
        on_delete=models.SET_NULL,
        related_name='items',
        null=True,
        blank=True,
    )
    prep_station = models.ForeignKey(
        'restaurants.PrepStation',
        on_delete=models.SET_NULL,
        related_name='catalog_items',
        null=True,
        blank=True,
    )
    name = models.CharField(max_length=255)
    mxik_code = models.CharField(max_length=17, blank=True, db_index=True)
    mxik_name = models.CharField(max_length=512, blank=True)
    mxik_payload = models.JSONField(default=dict, blank=True)
    requires_marking = models.BooleanField(default=False)
    marking_gtin = models.CharField(max_length=32, blank=True, db_index=True)
    image_url = models.URLField(blank=True, null=True)
    image_source = models.CharField(max_length=32, blank=True, choices=ImageSource.choices)
    image_file = models.ImageField(
        blank=True,
        null=True,
        storage=CatalogItemImageStorage,
        upload_to=catalog_item_image_upload_to,
    )
    description = models.TextField(blank=True)
    item_type = models.CharField(max_length=16, choices=ItemType.choices, default=ItemType.PRODUCT)
    price = models.PositiveIntegerField(default=0)
    sale_unit = models.CharField(max_length=16, choices=SaleUnit.choices, default=SaleUnit.PIECE)
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    is_stoplisted = models.BooleanField(default=False)
    archived_at = models.DateTimeField(null=True, blank=True, db_index=True)
    modifier_groups = models.ManyToManyField(
        'catalog.ModifierGroup',
        through='catalog.CatalogItemModifierGroup',
        related_name='catalog_items',
        blank=True,
    )

    class Meta:
        ordering = ('sort_order', 'name')

    def __str__(self):
        return self.name
