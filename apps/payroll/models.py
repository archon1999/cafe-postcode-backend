from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q

from common.models import BaseModel


MONEY_VALIDATORS = [MinValueValidator(Decimal('0.01'))]


class CompensationRate(BaseModel):
    class Type(models.TextChoices):
        HOURLY = 'hourly', 'Hourly'
        DAILY = 'daily', 'Daily'
        MONTHLY = 'monthly', 'Monthly'

    restaurant = models.ForeignKey('restaurants.Restaurant', on_delete=models.CASCADE, related_name='compensation_rates')
    employee = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='compensation_rates')
    rate_type = models.CharField(max_length=16, choices=Type.choices)
    amount = models.DecimalField(max_digits=14, decimal_places=2, validators=MONEY_VALIDATORS)
    effective_from = models.DateField()
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='authored_compensation_rates')

    class Meta:
        ordering = ('-effective_from', '-created_at')
        constraints = [
            models.UniqueConstraint(fields=('restaurant', 'employee', 'effective_from'), name='payroll_rate_effective_date_uniq'),
        ]


class PayrollPeriod(BaseModel):
    class Status(models.TextChoices):
        OPEN = 'open', 'Open'
        LOCKED = 'locked', 'Locked'

    restaurant = models.ForeignKey('restaurants.Restaurant', on_delete=models.CASCADE, related_name='payroll_periods')
    label = models.CharField(max_length=120)
    start_date = models.DateField()
    end_date = models.DateField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.OPEN)
    locked_at = models.DateTimeField(null=True, blank=True)
    locked_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name='locked_payroll_periods')

    class Meta:
        ordering = ('-start_date',)
        constraints = [
            models.UniqueConstraint(fields=('restaurant', 'start_date', 'end_date'), name='payroll_period_dates_uniq'),
            models.CheckConstraint(check=Q(end_date__gte=models.F('start_date')), name='payroll_period_order_ck'),
        ]


class KpiRule(BaseModel):
    restaurant = models.ForeignKey('restaurants.Restaurant', on_delete=models.CASCADE, related_name='payroll_kpi_rules')
    role = models.ForeignKey('users.Role', on_delete=models.PROTECT, null=True, blank=True, related_name='payroll_kpi_rules')
    percent = models.DecimalField(max_digits=6, decimal_places=3, validators=[MinValueValidator(Decimal('0'))])
    effective_from = models.DateField()
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='authored_payroll_kpi_rules')

    class Meta:
        ordering = ('-effective_from', '-created_at')
        constraints = [
            models.UniqueConstraint(fields=('restaurant', 'role', 'effective_from'), name='payroll_kpi_role_date_uniq'),
            models.UniqueConstraint(fields=('restaurant', 'effective_from'), condition=Q(role__isnull=True), name='payroll_kpi_default_date_uniq'),
        ]


class PayrollAdjustment(BaseModel):
    class Kind(models.TextChoices):
        KPI = 'kpi', 'KPI'
        BONUS = 'bonus', 'Bonus'
        ADVANCE = 'advance', 'Advance'
        PENALTY = 'penalty', 'Penalty'
        DEDUCTION = 'deduction', 'Deduction'
        CORRECTION_CREDIT = 'correction_credit', 'Correction credit'
        CORRECTION_DEBIT = 'correction_debit', 'Correction debit'

    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        APPROVED = 'approved', 'Approved'
        REJECTED = 'rejected', 'Rejected'
        SUPERSEDED = 'superseded', 'Superseded'

    class Origin(models.TextChoices):
        MANUAL = 'manual', 'Manual'
        POS = 'pos', 'POS'

    restaurant = models.ForeignKey('restaurants.Restaurant', on_delete=models.CASCADE, related_name='payroll_adjustments')
    period = models.ForeignKey(PayrollPeriod, on_delete=models.PROTECT, related_name='adjustments')
    employee = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='payroll_adjustments')
    kind = models.CharField(max_length=24, choices=Kind.choices)
    origin = models.CharField(max_length=12, choices=Origin.choices, default=Origin.MANUAL)
    amount = models.DecimalField(max_digits=14, decimal_places=2, validators=MONEY_VALIDATORS)
    reason = models.TextField()
    evidence = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='authored_payroll_adjustments')
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name='approved_payroll_adjustments')
    approved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ('created_at',)
        constraints = [
            models.UniqueConstraint(fields=('period', 'employee'), condition=Q(origin='pos', status='approved'), name='payroll_one_approved_pos_kpi_uniq'),
        ]


class PayrollRun(BaseModel):
    class Status(models.TextChoices):
        DRAFT = 'draft', 'Draft'
        LOCKED = 'locked', 'Locked'

    restaurant = models.ForeignKey('restaurants.Restaurant', on_delete=models.CASCADE, related_name='payroll_runs')
    period = models.ForeignKey(PayrollPeriod, on_delete=models.PROTECT, related_name='runs')
    employee = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='payroll_runs')
    version = models.PositiveIntegerField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    lines = models.JSONField(default=list)
    source_signature = models.CharField(max_length=64)
    total = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0'))
    built_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='built_payroll_runs')
    locked_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name='finalized_payroll_runs')
    locked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ('-version',)
        constraints = [
            models.UniqueConstraint(fields=('period', 'employee', 'version'), name='payroll_run_version_uniq'),
        ]


class PayrollPayout(BaseModel):
    class Method(models.TextChoices):
        CASH = 'cash', 'Cash'
        EXTERNAL_TRANSFER = 'external_transfer', 'External transfer'

    restaurant = models.ForeignKey('restaurants.Restaurant', on_delete=models.CASCADE, related_name='payroll_payouts')
    period = models.ForeignKey(PayrollPeriod, on_delete=models.PROTECT, related_name='payouts')
    employee = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='payroll_payouts')
    amount = models.DecimalField(max_digits=14, decimal_places=2, validators=MONEY_VALIDATORS)
    method = models.CharField(max_length=24, choices=Method.choices)
    paid_at = models.DateTimeField()
    note = models.TextField(blank=True)
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='recorded_payroll_payouts')
    voided_at = models.DateTimeField(null=True, blank=True)
    voided_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name='voided_payroll_payouts')
    void_reason = models.TextField(blank=True)

    class Meta:
        ordering = ('-paid_at', '-created_at')
