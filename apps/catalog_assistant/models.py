from django.conf import settings
from django.db import models
from common.models import BaseModel


class CatalogDraft(BaseModel):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    restaurant = models.ForeignKey('restaurants.Restaurant', on_delete=models.CASCADE)
    rows = models.JSONField(default=list)
    warnings = models.JSONField(default=list)
    revision = models.PositiveIntegerField(default=1)
    expires_at = models.DateTimeField()
    committed_at = models.DateTimeField(null=True, blank=True)
    result = models.JSONField(default=dict)


class ManagementBotAccount(BaseModel):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    telegram_user_id = models.BigIntegerField(unique=True)
    chat_id = models.BigIntegerField()
    restaurant = models.ForeignKey('restaurants.Restaurant', null=True, blank=True, on_delete=models.SET_NULL)
    state = models.JSONField(default=dict)


class ManagementBotLink(BaseModel):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    token_hash = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)


class ManagementBotUpdate(BaseModel):
    update_id = models.BigIntegerField(unique=True)
    payload = models.JSONField(default=dict)
    status = models.CharField(max_length=16, default='pending')
    error_code = models.CharField(max_length=80, blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)
