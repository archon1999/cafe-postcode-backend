import secrets
import string

from django.db import models

from common.models import BaseModel


AUTH_CODE_ALPHABET = string.ascii_letters + string.digits


def generate_restaurant_auth_code():
    return ''.join(secrets.choice(AUTH_CODE_ALPHABET) for _ in range(6))


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
    service_fee_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    last_order_number = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    activated_at = models.DateTimeField(null=True, blank=True)
    deactivated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ('name',)

    def __str__(self):
        return self.name
