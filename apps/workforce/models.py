from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q

from common.models import BaseModel


class GeofenceConfig(BaseModel):
    restaurant = models.OneToOneField('restaurants.Restaurant', on_delete=models.CASCADE, related_name='workforce_geofence')
    workforce_enabled = models.BooleanField(default=False)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    radius_meters = models.PositiveIntegerField(default=150, validators=[MinValueValidator(25), MaxValueValidator(5000)])
    enabled = models.BooleanField(default=False)


class WeeklyScheduleTemplate(BaseModel):
    restaurant = models.ForeignKey('restaurants.Restaurant', on_delete=models.CASCADE, related_name='workforce_templates')
    employee = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='workforce_templates')
    weekday = models.PositiveSmallIntegerField(validators=[MaxValueValidator(6)])
    start_time = models.TimeField()
    end_time = models.TimeField()
    unpaid_break_minutes = models.PositiveSmallIntegerField(default=0)
    effective_from = models.DateField()
    effective_until = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ('employee__full_name', 'weekday', 'start_time')
        indexes = [models.Index(fields=['restaurant', 'employee', 'weekday'], name='workforce_template_lookup_idx')]


class Shift(BaseModel):
    class Status(models.TextChoices):
        DRAFT = 'draft', 'Draft'
        PUBLISHED = 'published', 'Published'
        CANCELLED = 'cancelled', 'Cancelled'

    restaurant = models.ForeignKey('restaurants.Restaurant', on_delete=models.CASCADE, related_name='workforce_shifts')
    employee = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='workforce_shifts')
    template = models.ForeignKey(WeeklyScheduleTemplate, on_delete=models.SET_NULL, null=True, blank=True, related_name='shifts')
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    unpaid_break_minutes = models.PositiveSmallIntegerField(default=0)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    note = models.CharField(max_length=500, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    published_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='published_workforce_shifts')

    class Meta:
        ordering = ('starts_at',)
        indexes = [models.Index(fields=['restaurant', 'employee', 'starts_at'], name='workforce_shift_lookup_idx')]


class AttendancePunch(BaseModel):
    class Type(models.TextChoices):
        IN = 'in', 'In'
        OUT = 'out', 'Out'
        BREAK_START = 'break_start', 'Break start'
        BREAK_END = 'break_end', 'Break end'

    class Source(models.TextChoices):
        PWA = 'pwa', 'PWA'
        HIKVISION = 'hikvision', 'Hikvision'

    class GeoStatus(models.TextChoices):
        INSIDE = 'inside', 'Inside'
        OUTSIDE = 'outside', 'Outside'
        UNAVAILABLE = 'unavailable', 'Unavailable'
        UNCONFIGURED = 'unconfigured', 'Unconfigured'

    restaurant = models.ForeignKey('restaurants.Restaurant', on_delete=models.CASCADE, related_name='workforce_punches')
    employee = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='workforce_punches')
    work_date = models.DateField(db_index=True)
    type = models.CharField(max_length=16, choices=Type.choices)
    source = models.CharField(max_length=16, choices=Source.choices)
    source_event_id = models.CharField(max_length=128)
    occurred_at = models.DateTimeField(db_index=True)
    client_recorded_at = models.DateTimeField(null=True, blank=True)
    device_recorded_at = models.DateTimeField(null=True, blank=True)
    clock_skew_seconds = models.BigIntegerField(null=True, blank=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    accuracy_meters = models.PositiveIntegerField(null=True, blank=True)
    distance_meters = models.PositiveIntegerField(null=True, blank=True)
    geo_status = models.CharField(max_length=16, choices=GeoStatus.choices, default=GeoStatus.UNAVAILABLE)
    provisional = models.BooleanField(default=False)
    requires_review = models.BooleanField(default=False)
    review_reasons = models.JSONField(default=list, blank=True)
    selfie_data = models.BinaryField(null=True, blank=True)
    selfie_mime_type = models.CharField(max_length=32, blank=True)

    class Meta:
        ordering = ('occurred_at', 'created_at')
        constraints = [
            models.UniqueConstraint(fields=['restaurant', 'source', 'source_event_id'], name='workforce_punch_source_unique'),
        ]
        indexes = [models.Index(fields=['restaurant', 'employee', 'work_date'], name='workforce_punch_day_idx')]


class Timesheet(BaseModel):
    class Status(models.TextChoices):
        DRAFT = 'draft', 'Draft'
        APPROVED = 'approved', 'Approved'

    restaurant = models.ForeignKey('restaurants.Restaurant', on_delete=models.CASCADE, related_name='workforce_timesheets')
    employee = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='workforce_timesheets')
    work_date = models.DateField()
    shift = models.ForeignKey(Shift, on_delete=models.SET_NULL, null=True, blank=True, related_name='timesheets')
    period_start = models.DateTimeField(null=True, blank=True)
    period_end = models.DateTimeField(null=True, blank=True)
    break_minutes = models.PositiveIntegerField(default=0)
    approved_minutes = models.PositiveIntegerField(default=0)
    approved_shift_count = models.PositiveSmallIntegerField(default=0)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    requires_review = models.BooleanField(default=False)
    review_reasons = models.JSONField(default=list, blank=True)
    manager_note = models.CharField(max_length=1000, blank=True)
    manual_override = models.BooleanField(default=False)
    approved_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='approved_workforce_timesheets')

    class Meta:
        ordering = ('-work_date', 'employee__full_name')
        constraints = [models.UniqueConstraint(fields=['restaurant', 'employee', 'work_date'], name='workforce_timesheet_day_unique')]
        indexes = [models.Index(fields=['restaurant', 'work_date', 'status'], name='workforce_timesheet_period_idx')]


class CorrectionRequest(BaseModel):
    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        APPROVED = 'approved', 'Approved'
        REJECTED = 'rejected', 'Rejected'

    restaurant = models.ForeignKey('restaurants.Restaurant', on_delete=models.CASCADE, related_name='workforce_corrections')
    employee = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='workforce_corrections')
    work_date = models.DateField()
    proposed_start_at = models.DateTimeField()
    proposed_end_at = models.DateTimeField()
    proposed_break_minutes = models.PositiveIntegerField(default=0)
    reason = models.CharField(max_length=1000)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='reviewed_workforce_corrections')
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.CharField(max_length=1000, blank=True)

    class Meta:
        ordering = ('-created_at',)
        constraints = [models.CheckConstraint(condition=Q(proposed_end_at__gt=models.F('proposed_start_at')), name='workforce_correction_end_after_start')]
