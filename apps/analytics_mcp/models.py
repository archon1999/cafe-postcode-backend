import uuid

from django.conf import settings
from django.db import models


class AnalyticsConnection(models.Model):
    """A consent snapshot; later restaurant additions require a new consent."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    application = models.ForeignKey(
        "oauth2_provider.Application", on_delete=models.CASCADE
    )
    restaurant_ids = models.JSONField(default=list)
    resource = models.URLField(max_length=500)
    token_family = models.UUIDField(null=True, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)


class AuthorizationBinding(models.Model):
    grant = models.OneToOneField("oauth2_provider.Grant", on_delete=models.CASCADE)
    connection = models.ForeignKey(AnalyticsConnection, on_delete=models.CASCADE)


class AccessBinding(models.Model):
    access_token = models.OneToOneField(
        "oauth2_provider.AccessToken", on_delete=models.CASCADE
    )
    connection = models.ForeignKey(AnalyticsConnection, on_delete=models.CASCADE)


class ReportSnapshot(models.Model):
    """Shared across workers, bounded TTL, never an authorization capability."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    connection = models.ForeignKey(AnalyticsConnection, on_delete=models.CASCADE)
    restaurant_ids = models.JSONField(default=list)
    payload = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(db_index=True)
