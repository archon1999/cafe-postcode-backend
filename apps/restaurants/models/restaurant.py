import secrets
import string
import uuid
from pathlib import Path

from django.db import models

from common.storages import RestaurantAuthBackgroundStorage
from common.models import BaseModel


AUTH_CODE_ALPHABET = string.ascii_letters + string.digits


def generate_restaurant_auth_code():
    return ''.join(secrets.choice(AUTH_CODE_ALPHABET) for _ in range(6))


def restaurant_auth_background_upload_to(instance, filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    return f'{instance.id}/{uuid.uuid4().hex}{suffix}'


class Restaurant(BaseModel):
    business_partner = models.ForeignKey(
        'platform.BusinessPartner',
        on_delete=models.SET_NULL,
        related_name='restaurants',
        null=True,
        blank=True,
    )
    name = models.CharField(max_length=255)
    legal_name = models.CharField(max_length=255, blank=True)
    tax_number = models.CharField(max_length=60, blank=True)
    phone = models.CharField(max_length=30, blank=True)
    address = models.CharField(max_length=255, blank=True)
    faktura_payload = models.JSONField(default=dict, blank=True)
    currency = models.CharField(max_length=10, default='UZS')
    auth_code = models.CharField(max_length=6, unique=True, default=generate_restaurant_auth_code)
    service_fee_enabled = models.BooleanField(default=False)
    service_fee_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    vat_enabled = models.BooleanField(default=False)
    vat_percent = models.DecimalField(max_digits=5, decimal_places=2, default=12)
    pos_auth_background_image = models.ImageField(
        blank=True,
        null=True,
        storage=RestaurantAuthBackgroundStorage,
        upload_to=restaurant_auth_background_upload_to,
    )
    last_order_number = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    activated_at = models.DateTimeField(null=True, blank=True)
    deactivated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ('name',)

    def __str__(self):
        return self.name
