from django.conf import settings
from django.db import models
from django.utils import timezone

from common.models import BaseModel


class ExpenseCategory(BaseModel):
    restaurant = models.ForeignKey(
        'restaurants.Restaurant',
        on_delete=models.CASCADE,
        related_name='expense_categories',
    )
    name = models.CharField(max_length=120)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name='expense_categories_created',
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ('sort_order', 'name')
        constraints = [
            models.UniqueConstraint(
                fields=('restaurant', 'name'),
                name='expense_category_restaurant_name_uniq',
            ),
        ]
        indexes = [
            models.Index(
                fields=('restaurant', 'is_active', 'sort_order'),
                name='expense_category_scope_idx',
            ),
        ]


class CashExpense(BaseModel):
    class Status(models.TextChoices):
        POSTED = 'posted', 'Posted'
        VOIDED = 'voided', 'Voided'

    restaurant = models.ForeignKey(
        'restaurants.Restaurant',
        on_delete=models.CASCADE,
        related_name='cash_expenses',
    )
    cash_shift = models.ForeignKey(
        'billing.CashShift',
        on_delete=models.PROTECT,
        related_name='expenses',
    )
    cash_desk = models.ForeignKey(
        'restaurants.CashDesk',
        on_delete=models.PROTECT,
        related_name='cash_expenses',
    )
    category = models.ForeignKey(
        ExpenseCategory,
        on_delete=models.PROTECT,
        related_name='expenses',
    )
    amount = models.PositiveBigIntegerField()
    comment = models.CharField(max_length=500, blank=True)
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name='cash_expenses_received',
        null=True,
        blank=True,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='cash_expenses_created',
    )
    category_name_snapshot = models.CharField(max_length=120)
    recipient_name_snapshot = models.CharField(max_length=150, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.POSTED)
    occurred_at = models.DateTimeField(default=timezone.now)
    voided_at = models.DateTimeField(null=True, blank=True)
    voided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name='cash_expenses_voided',
        null=True,
        blank=True,
    )
    void_reason = models.CharField(max_length=500, blank=True)
    edge_operation_id = models.CharField(max_length=128, unique=True, null=True, blank=True)

    class Meta:
        ordering = ('-occurred_at', '-created_at')
        indexes = [
            models.Index(
                fields=('restaurant', 'occurred_at'),
                name='cash_expense_scope_time_idx',
            ),
            models.Index(
                fields=('cash_shift', 'status'),
                name='cash_expense_shift_status_idx',
            ),
            models.Index(
                fields=('category', 'occurred_at'),
                name='cash_expense_category_time_idx',
            ),
        ]
