"""Metadata-only accounting for paid cloud AI requests; source content is never stored."""
from django.conf import settings
from django.db import models
from common.models import BaseModel


class AIUsageLog(BaseModel):
    class Feature(models.TextChoices):
        CATALOG_MENU = 'catalog_menu', 'Catalog menu'
        INVENTORY_ANALYSIS = 'inventory_analysis', 'Inventory analysis'
        INVENTORY_DOCUMENT = 'inventory_document', 'Inventory document'
        SERVICE_FEE_FORMULA = 'service_fee_formula', 'Service fee formula'

    class Status(models.TextChoices):
        SUCCESS = 'success', 'Success'
        ERROR = 'error', 'Error'

    class Source(models.TextChoices):
        LIVE = 'live', 'Live provider audit'
        CATALOG_DRAFT = 'catalog_draft', 'Recovered catalog draft'

    restaurant = models.ForeignKey('restaurants.Restaurant', null=True, blank=True, on_delete=models.SET_NULL, related_name='ai_usage_logs')
    business_partner = models.ForeignKey('platform.BusinessPartner', null=True, blank=True, on_delete=models.SET_NULL, related_name='ai_usage_logs')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='ai_usage_logs')
    restaurant_name = models.CharField(max_length=255, blank=True)
    business_partner_name = models.CharField(max_length=255, blank=True)
    user_name = models.CharField(max_length=255, blank=True)
    feature = models.CharField(max_length=32, choices=Feature.choices)
    provider = models.CharField(max_length=20, default='openai', editable=False)
    model = models.CharField(max_length=120)
    status = models.CharField(max_length=12, choices=Status.choices)
    input_tokens = models.PositiveBigIntegerField(null=True, blank=True)
    cached_input_tokens = models.PositiveBigIntegerField(null=True, blank=True)
    output_tokens = models.PositiveBigIntegerField(null=True, blank=True)
    total_tokens = models.PositiveBigIntegerField(null=True, blank=True)
    estimated_cost_usd = models.DecimalField(max_digits=24, decimal_places=12, null=True, blank=True)
    pricing = models.JSONField(default=dict, blank=True)
    duration_ms = models.PositiveIntegerField(default=0, null=True, blank=True)
    request_id = models.CharField(max_length=128, blank=True)
    provider_status = models.CharField(max_length=20, blank=True)
    error_code = models.CharField(max_length=64, blank=True)
    error_summary = models.CharField(max_length=255, blank=True)
    source = models.CharField(max_length=24, choices=Source.choices, default=Source.LIVE, db_default=Source.LIVE, db_index=True)
    recovery_key = models.CharField(max_length=200, null=True, blank=True, unique=True, editable=False)
    recovered_at = models.DateTimeField(null=True, blank=True, editable=False)
    evidence = models.JSONField(default=dict, db_default={}, blank=True, editable=False)

    class Meta:
        ordering = ('-created_at', '-id')
        indexes = [
            models.Index(fields=['created_at'], name='ai_usage_created_idx'),
            models.Index(fields=['restaurant', 'created_at'], name='ai_usage_rest_date_idx'),
            models.Index(fields=['business_partner', 'created_at'], name='ai_usage_partner_date_idx'),
            models.Index(fields=['feature', 'status', 'created_at'], name='ai_usage_feature_date_idx'),
        ]
