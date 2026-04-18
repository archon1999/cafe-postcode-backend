from __future__ import annotations

from datetime import date

from dateutil.relativedelta import relativedelta
from django.db import transaction
from django.db.utils import OperationalError, ProgrammingError
from django.utils import timezone

from apps.platform.models import RestaurantEntitlement
from apps.restaurants.helpers import get_restaurant_model

from .restaurant_balances import (
    create_restaurant_renewal_charge,
    get_restaurant_current_balance,
    get_restaurant_next_charge_amount,
)

Restaurant = get_restaurant_model()

EXPIRY_SCHEDULE_NAME = 'platform.expire_restaurant_entitlements'
EXPIRY_SCHEDULE_FUNC = 'apps.platform.services.restaurant_subscriptions.expire_restaurant_entitlements'


def add_billing_period(value: date, billing_period: str) -> date:
    if billing_period == RestaurantEntitlement.BillingPeriod.MONTHLY:
        return value + relativedelta(months=1)
    if billing_period == RestaurantEntitlement.BillingPeriod.YEARLY:
        return value + relativedelta(years=1)
    raise ValueError(f'Unsupported billing period: {billing_period}')


def deactivate_restaurant_access(*, restaurant, entitlement=None, deactivated_at=None) -> None:
    timestamp = deactivated_at or timezone.now()
    target_entitlement = entitlement if entitlement is not None else getattr(restaurant, 'entitlement', None)

    restaurant.is_active = False
    restaurant.deactivated_at = timestamp
    restaurant.save(update_fields=['is_active', 'deactivated_at', 'updated_at'])

    if target_entitlement is not None and target_entitlement.is_active:
        target_entitlement.is_active = False
        target_entitlement.save(update_fields=['is_active', 'updated_at'])


@transaction.atomic
def extend_restaurant_entitlement(*, restaurant, entitlement, today=None):
    if not entitlement.billing_period:
        raise ValueError('Restaurant entitlement billing period is not configured.')

    base_date = today or timezone.localdate()
    if entitlement.expires_on and entitlement.expires_on >= base_date:
        next_expiry = add_billing_period(entitlement.expires_on, entitlement.billing_period)
    else:
        entitlement.starts_on = base_date
        next_expiry = add_billing_period(base_date, entitlement.billing_period)

    entitlement.expires_on = next_expiry
    entitlement.is_active = True
    entitlement.save(update_fields=['starts_on', 'expires_on', 'is_active', 'updated_at'])

    if not restaurant.is_active:
        now = timezone.now()
        restaurant.is_active = True
        restaurant.activated_at = now
        restaurant.deactivated_at = None
        restaurant.save(update_fields=['is_active', 'activated_at', 'deactivated_at', 'updated_at'])

    return entitlement


@transaction.atomic
def try_auto_renew_restaurant_entitlement(*, restaurant, entitlement, today=None) -> bool:
    charge_amount = get_restaurant_next_charge_amount(entitlement)
    if charge_amount is None:
        return False

    current_balance = get_restaurant_current_balance(restaurant)
    if current_balance < charge_amount:
        return False

    extend_restaurant_entitlement(restaurant=restaurant, entitlement=entitlement, today=today)
    if charge_amount > 0:
        create_restaurant_renewal_charge(
            restaurant=restaurant,
            amount=charge_amount,
            period_start=entitlement.starts_on,
            period_end=entitlement.expires_on,
        )
    return True


def expire_restaurant_entitlements() -> int:
    today = timezone.localdate()
    expired_entitlements = (
        RestaurantEntitlement.objects.select_related('restaurant')
        .filter(is_active=True, expires_on__lt=today, restaurant__is_active=True)
        .order_by('restaurant__name')
    )

    expired_count = 0
    for entitlement in expired_entitlements:
        if not try_auto_renew_restaurant_entitlement(
            restaurant=entitlement.restaurant,
            entitlement=entitlement,
            today=today,
        ):
            deactivate_restaurant_access(restaurant=entitlement.restaurant, entitlement=entitlement)
        expired_count += 1

    return expired_count


def ensure_expiry_schedule() -> bool:
    from django_q.models import Schedule

    try:
        Schedule.objects.update_or_create(
            name=EXPIRY_SCHEDULE_NAME,
            func=EXPIRY_SCHEDULE_FUNC,
            defaults={
                'schedule_type': Schedule.HOURLY,
                'repeats': -1,
                'next_run': timezone.now(),
            },
        )
    except (ProgrammingError, OperationalError):
        return False

    return True
