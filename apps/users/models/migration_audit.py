from django.db import models


class LegacyFieldMigrationAudit(models.Model):
    """Durable aggregate audit recorded before obsolete employee fields are dropped."""

    id = models.BigAutoField(primary_key=True)
    restaurant_id = models.UUIDField(null=True, blank=True, db_index=True)
    employee_count = models.PositiveIntegerField(default=0)
    rows_with_values = models.PositiveIntegerField(default=0)
    field_counts = models.JSONField(default=dict)
    snapshots = models.JSONField(default=list)
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('restaurant_id',)
