from django.db import models

from common.models import BaseModel


class BusinessPartner(BaseModel):
    class Status(models.TextChoices):
        DRAFT = 'draft', 'Draft'
        ACTIVE = 'active', 'Active'
        INACTIVE = 'inactive', 'Inactive'

    inn = models.CharField(max_length=32, unique=True)
    company_name = models.CharField(max_length=255)
    legal_name = models.CharField(max_length=255, blank=True)
    director_name = models.CharField(max_length=255, blank=True)
    phone = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)
    address = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    owner_user = models.OneToOneField('users.User', on_delete=models.SET_NULL, related_name='business_partner_profile', null=True, blank=True)
    activated_at = models.DateTimeField(null=True, blank=True)
    deactivated_at = models.DateTimeField(null=True, blank=True)
    faktura_payload = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ('company_name',)

    def __str__(self):
        return self.company_name
