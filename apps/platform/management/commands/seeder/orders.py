from datetime import timedelta

from django.utils import timezone

from apps.floor.models import DiningTable, TableSession
from apps.kitchen.models import KitchenTicket
from apps.sales.models import Order, OrderItem
from apps.billing.models import Payment, Receipt


def _set_timestamp(instance, *, created_at, updated_at):
    instance.__class__.objects.filter(pk=instance.pk).update(created_at=created_at, updated_at=updated_at)


def seed_orders(
    *,
    restaurant,
    order_specs,
    users_by_username,
    items_by_code,
    halls_by_code,
    tables_by_key,
    cash_desk,
    distribution_points,
):
    now = timezone.now()

    for index, spec in enumerate(order_specs):
        opened_at = now - timedelta(hours=index + 1)
        closed_at = opened_at + timedelta(minutes=40) if spec.closed else None
        opened_by = users_by_username[spec.opened_by]
        cashier = users_by_username[spec.cashier] if spec.cashier else None

        table_session = None
        if spec.channel == Order.Channel.HALL and spec.hall_code and spec.table_number is not None:
            hall = halls_by_code[spec.hall_code]
            table = tables_by_key[(spec.hall_code, spec.table_number)]
            table.status = DiningTable.Status.AVAILABLE if spec.closed else DiningTable.Status.OCCUPIED
            table.save(update_fields=['status', 'updated_at'])
            table_session = TableSession.objects.create(
                restaurant=restaurant,
                hall=hall,
                table=table,
                opened_by=opened_by,
                assigned_waiter=opened_by,
                guest_count=spec.guest_count,
                status=TableSession.Status.CLOSED if spec.closed else TableSession.Status.OPEN,
                closed_at=closed_at,
            )
            _set_timestamp(
                table_session,
                created_at=opened_at,
                updated_at=closed_at or opened_at,
            )

        distribution_kind = DistributionPointKind.TAKEAWAY if spec.channel == Order.Channel.TAKEAWAY else DistributionPointKind.HALL
        distribution_point = distribution_points.get(distribution_kind)
        order = Order.objects.create(
            restaurant=restaurant,
            table_session=table_session,
            distribution_point=distribution_point,
            opened_by=opened_by,
            cashier=cashier,
            order_number=spec.number,
            channel=spec.channel,
            status=Order.Status.CLOSED if spec.closed else Order.Status.SUBMITTED,
            guest_count=spec.guest_count,
            note=spec.note,
            closed_at=closed_at,
        )

        prep_stations = {}
        for item_code in spec.item_codes:
            item = items_by_code[item_code]
            order_item = OrderItem.objects.create(
                order=order,
                catalog_item=item,
                prep_station=item.prep_station,
                created_by=opened_by,
                quantity=1,
                unit_price=item.price,
                status=OrderItem.Status.DONE if spec.closed else OrderItem.Status.COOKING,
            )
            _set_timestamp(
                order_item,
                created_at=opened_at,
                updated_at=closed_at or opened_at,
            )
            if item.prep_station_id:
                prep_stations[item.prep_station_id] = item.prep_station

        order.recalculate_totals()
        _set_timestamp(
            order,
            created_at=opened_at,
            updated_at=closed_at or opened_at,
        )

        if spec.closed:
            payment = Payment.objects.create(
                order=order,
                cash_desk=cash_desk,
                received_by=cashier,
                method=Payment.Method.CASH,
                amount=order.total,
                status=Payment.Status.SUCCEEDED,
                external_ref=f'DEMO-{order.order_number}',
                provider_payload={'provider': 'mock-payment'},
                paid_at=closed_at,
            )
            _set_timestamp(payment, created_at=closed_at, updated_at=closed_at)

            receipt = Receipt.objects.create(
                order=order,
                payment=payment,
                kind=Receipt.Kind.FISCAL,
                status=Receipt.Status.SENT,
                provider='mock-fiscal',
                payload={'receipt_number': f'REC-{order.order_number}'},
            )
            _set_timestamp(receipt, created_at=closed_at, updated_at=closed_at)
            continue

        for prep_station in prep_stations.values():
            ticket = KitchenTicket.objects.create(
                restaurant=restaurant,
                order=order,
                prep_station=prep_station,
                status=KitchenTicket.Status.COOKING,
                routed_via=KitchenTicket.RouteMode.BOTH,
                is_printed=True,
                printed_payload={'provider': 'mock-printer'},
            )
            _set_timestamp(ticket, created_at=opened_at, updated_at=opened_at)


class DistributionPointKind:
    HALL = 'hall'
    TAKEAWAY = 'takeaway'
