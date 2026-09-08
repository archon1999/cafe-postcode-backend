"""Sold lines belong to the shift receiving the order's final payment.

As in the daily report, cancelled lines are excluded and refunds are reported
separately. A split payment must never multiply product quantities.
"""
from decimal import Decimal

from django.db.models import OuterRef, Prefetch, Subquery

from apps.billing.models import Payment
from apps.integrations.services.fiscal_total_allocation import allocate_fiscal_totals
from apps.sales.models import Order, OrderItem


def shift_sold_orders(shift):
    final_payment = Payment.objects.filter(
        order_id=OuterRef('pk'), status=Payment.Status.SUCCEEDED,
    ).order_by('-paid_at', '-created_at', '-id')
    orders = Order.objects.filter(
        restaurant=shift.cash_desk.restaurant, status=Order.Status.CLOSED,
    ).annotate(final_shift=Subquery(final_payment.values('cash_shift_id')[:1]))
    return orders.filter(final_shift=shift.pk)


def build_shift_sold_items(shift):
    items = OrderItem.objects.exclude(status=OrderItem.Status.CANCELLED).select_related(
        'catalog_item',
    ).order_by('created_at', 'id')
    orders = shift_sold_orders(shift).prefetch_related(Prefetch('items', queryset=items))
    grouped = {}
    for order in orders:
        lines = list(order.items.all())
        totals = [int(item.line_total) for item in lines]
        if order.total_override is not None:
            # Discount service fees proportionally too, without counting them as products.
            service_fee = max(int(order.calculated_total) - int(order.subtotal), 0)
            totals = allocate_fiscal_totals(
                [*totals, service_fee] if service_fee else totals,
                target_total=int(order.total),
            )[:len(lines)]
        for item, revenue in zip(lines, totals):
            key = (str(item.catalog_item_id), item.sale_unit)
            row = grouped.setdefault(key, dict(
                catalog_item_id=key[0], name=item.catalog_item.name,
                sale_unit=item.sale_unit, quantity=Decimal(0), revenue=0,
            ))
            row['quantity'] += item.quantity
            row['revenue'] += revenue
    rows = sorted(grouped.values(), key=lambda row: (
        -row['revenue'], row['name'], row['catalog_item_id'], row['sale_unit'],
    ))
    return [dict(row, quantity=float(row['quantity'])) for row in rows]
