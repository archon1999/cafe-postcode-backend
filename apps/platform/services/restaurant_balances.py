from __future__ import annotations

from decimal import Decimal

from django.db import models, transaction

from apps.platform.helpers import get_restaurant_balance_transaction_model
from apps.restaurants.helpers import get_restaurant_model

Restaurant = get_restaurant_model()
RestaurantBalanceTransaction = get_restaurant_balance_transaction_model()

ZERO_AMOUNT = Decimal('0.00')


def get_restaurant_current_balance(restaurant) -> Decimal:
    current_balance = (
        RestaurantBalanceTransaction.objects.filter(restaurant=restaurant)
        .aggregate(total=models.Sum('amount'))
        .get('total')
    )
    return current_balance if current_balance is not None else ZERO_AMOUNT


def get_restaurant_next_charge_amount(entitlement) -> Decimal | None:
    if entitlement is None or not entitlement.billing_period:
        return None
    if entitlement.billing_period == entitlement.BillingPeriod.MONTHLY:
        return entitlement.monthly_price
    if entitlement.billing_period == entitlement.BillingPeriod.YEARLY:
        return entitlement.yearly_price
    return None


def get_restaurant_balance_summary(restaurant, *, entitlement=None) -> dict:
    target_entitlement = entitlement if entitlement is not None else getattr(restaurant, 'entitlement', None)
    current_balance = get_restaurant_current_balance(restaurant)
    next_charge_amount = get_restaurant_next_charge_amount(target_entitlement)
    next_charge_on = getattr(target_entitlement, 'expires_on', None)
    last_top_up_at = (
        RestaurantBalanceTransaction.objects.filter(
            restaurant=restaurant,
            kind=RestaurantBalanceTransaction.Kind.TOP_UP,
        )
        .order_by('-created_at')
        .values_list('created_at', flat=True)
        .first()
    )

    next_period_status = None
    if next_charge_amount is not None and next_charge_on is not None:
        next_period_status = 'active' if current_balance >= next_charge_amount else 'inactive'

    return {
        'current_balance': current_balance,
        'next_charge_amount': next_charge_amount,
        'next_charge_on': next_charge_on,
        'next_period_status': next_period_status,
        'last_top_up_at': last_top_up_at,
    }


def _normalize_positive_amount(amount: Decimal | str | int | float) -> Decimal:
    normalized = amount if isinstance(amount, Decimal) else Decimal(str(amount))
    if normalized <= ZERO_AMOUNT:
        raise ValueError('Amount must be positive.')
    return normalized


@transaction.atomic
def create_restaurant_balance_transaction(
    *,
    restaurant,
    kind: str,
    amount: Decimal | str | int | float,
    performed_by=None,
    note: str = '',
    period_start=None,
    period_end=None,
):
    Restaurant.objects.select_for_update().filter(pk=restaurant.pk).exists()
    normalized_amount = amount if isinstance(amount, Decimal) else Decimal(str(amount))
    current_balance = get_restaurant_current_balance(restaurant)
    balance_after = current_balance + normalized_amount
    return RestaurantBalanceTransaction.objects.create(
        restaurant=restaurant,
        kind=kind,
        amount=normalized_amount,
        balance_after=balance_after,
        performed_by=performed_by,
        note=note.strip(),
        period_start=period_start,
        period_end=period_end,
    )


def create_restaurant_top_up(*, restaurant, amount, performed_by=None, note: str = ''):
    normalized_amount = _normalize_positive_amount(amount)
    return create_restaurant_balance_transaction(
        restaurant=restaurant,
        kind=RestaurantBalanceTransaction.Kind.TOP_UP,
        amount=normalized_amount,
        performed_by=performed_by,
        note=note,
    )


def create_restaurant_renewal_charge(*, restaurant, amount, period_start=None, period_end=None):
    normalized_amount = _normalize_positive_amount(amount)
    return create_restaurant_balance_transaction(
        restaurant=restaurant,
        kind=RestaurantBalanceTransaction.Kind.RENEWAL_CHARGE,
        amount=-normalized_amount,
        period_start=period_start,
        period_end=period_end,
    )
