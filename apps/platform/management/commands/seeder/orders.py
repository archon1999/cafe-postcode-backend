from datetime import datetime, time, timedelta

from django.utils import timezone

from apps.billing.models import CashShift, Payment, Receipt
from apps.floor.models import DiningTable, TableSession
from apps.kitchen.models import KitchenTicket
from apps.sales.models import Order, OrderItem


def _set_timestamp(instance, *, created_at, updated_at):
    instance.__class__.objects.filter(pk=instance.pk).update(created_at=created_at, updated_at=updated_at)


def _at(target_date, hour: int, minute: int) -> datetime:
    naive = datetime.combine(target_date, time(hour=hour, minute=minute))
    return timezone.make_aware(naive, timezone.get_current_timezone())


def _iter_menu_items(items_by_code):
    return list(items_by_code.items())


def _pick_menu_slice(menu_entries, start: int, count: int) -> list[tuple[str, object]]:
    entries: list[tuple[str, object]] = []
    total = len(menu_entries)
    for offset in range(count):
        entries.append(menu_entries[(start + offset) % total])
    return entries


def _distribution_kind(channel: str) -> str:
    if channel == Order.Channel.HALL:
        return DistributionPointKind.HALL
    if channel == Order.Channel.TAKEAWAY:
        return DistributionPointKind.TAKEAWAY
    if channel == Order.Channel.DELIVERY:
        return DistributionPointKind.DELIVERY
    return DistributionPointKind.ONLINE


def _opening_cash(day_index: int) -> int:
    return 150000 + ((day_index % 5) * 25000)


def _closed_order_count(history, target_date) -> int:
    return history.weekend_closed_orders if target_date.weekday() >= 5 else history.weekday_closed_orders


def _build_shift(cash_desk, opened_by, *, opened_at, opening_cash_amount, note):
    shift = CashShift.objects.create(
        cash_desk=cash_desk,
        opened_by=opened_by,
        status=CashShift.Status.OPEN,
        opened_at=opened_at,
        opening_cash_amount=opening_cash_amount,
        notes_open=note,
    )
    _set_timestamp(shift, created_at=opened_at, updated_at=opened_at)
    return shift


def _finalize_shift(shift, totals, *, closed_by, closed_at=None):
    expected_cash = (shift.opening_cash_amount or 0) + totals['cash_total']
    if closed_at is None:
        shift.cash_total = totals['cash_total']
        shift.card_total = totals['card_total']
        shift.qr_total = totals['qr_total']
        shift.refund_total = 0
        shift.receipt_count = totals['receipt_count']
        shift.reprint_count = 0
        shift.expected_closing_cash_amount = expected_cash
        shift.save(
            update_fields=[
                'cash_total',
                'card_total',
                'qr_total',
                'refund_total',
                'receipt_count',
                'reprint_count',
                'expected_closing_cash_amount',
                'updated_at',
            ]
        )
        _set_timestamp(shift, created_at=shift.opened_at, updated_at=shift.opened_at + timedelta(hours=8))
        return shift

    variance = ((closed_at.day % 3) - 1) * 2000
    actual_cash = max(0, expected_cash + variance)
    shift.status = CashShift.Status.CLOSED
    shift.closed_by = closed_by
    shift.closed_at = closed_at
    shift.actual_closing_cash_amount = actual_cash
    shift.expected_closing_cash_amount = expected_cash
    shift.cash_difference_amount = actual_cash - expected_cash
    shift.cash_total = totals['cash_total']
    shift.card_total = totals['card_total']
    shift.qr_total = totals['qr_total']
    shift.refund_total = 0
    shift.receipt_count = totals['receipt_count']
    shift.reprint_count = 0
    shift.notes_close = 'Seeder closeout'
    shift.save(
        update_fields=[
            'status',
            'closed_by',
            'closed_at',
            'actual_closing_cash_amount',
            'expected_closing_cash_amount',
            'cash_difference_amount',
            'cash_total',
            'card_total',
            'qr_total',
            'refund_total',
            'receipt_count',
            'reprint_count',
            'notes_close',
            'updated_at',
        ]
    )
    _set_timestamp(shift, created_at=shift.opened_at, updated_at=closed_at)
    return shift


def _register_payment(order, *, cash_desk, shift, cashier, method, closed_at, receipt_ref):
    payment = Payment.objects.create(
        order=order,
        cash_desk=cash_desk,
        cash_shift=shift,
        received_by=cashier,
        method=method,
        amount=order.total,
        status=Payment.Status.SUCCEEDED,
        external_ref=f'DEMO-{order.order_number}',
        provider_payload={'provider': 'mock-payment', 'receipt_ref': receipt_ref},
        paid_at=closed_at,
    )
    _set_timestamp(payment, created_at=closed_at, updated_at=closed_at)

    receipt = Receipt.objects.create(
        order=order,
        payment=payment,
        kind=Receipt.Kind.FISCAL,
        status=Receipt.Status.SENT,
        provider='mock-fiscal',
        payload={'receipt_number': receipt_ref},
    )
    _set_timestamp(receipt, created_at=closed_at, updated_at=closed_at)
    return payment, receipt


def _make_closed_table_session(restaurant, *, hall, table, opened_by, opened_at, closed_at, guest_count, note):
    session = TableSession.objects.create(
        restaurant=restaurant,
        hall=hall,
        table=table,
        opened_by=opened_by,
        assigned_waiter=opened_by,
        guest_count=guest_count,
        status=TableSession.Status.CLOSED,
        note=note,
        closed_at=closed_at,
    )
    _set_timestamp(session, created_at=opened_at, updated_at=closed_at)
    table.status = DiningTable.Status.AVAILABLE
    table.save(update_fields=['status', 'updated_at'])
    return session


def _make_active_table_session(restaurant, *, hall, table, opened_by, opened_at, guest_count, note):
    session = TableSession.objects.create(
        restaurant=restaurant,
        hall=hall,
        table=table,
        opened_by=opened_by,
        assigned_waiter=opened_by,
        guest_count=guest_count,
        status=TableSession.Status.OPEN,
        note=note,
    )
    _set_timestamp(session, created_at=opened_at, updated_at=opened_at)
    table.status = DiningTable.Status.OCCUPIED
    table.save(update_fields=['status', 'updated_at'])
    return session


def _order_item_status(order_status: str, prep_station_id) -> str:
    if order_status == Order.Status.CLOSED:
        return OrderItem.Status.DONE
    if order_status == Order.Status.READY:
        return OrderItem.Status.DONE if prep_station_id else OrderItem.Status.SERVED
    if prep_station_id:
        return OrderItem.Status.COOKING
    return OrderItem.Status.NEW


def _create_order_items(order, *, opened_by, opened_at, selected_entries, order_status):
    prep_stations = {}
    for item_offset, (_code, item) in enumerate(selected_entries):
        quantity = 1 + ((order.order_number + item_offset) % 2)
        order_item = OrderItem.objects.create(
            order=order,
            catalog_item=item,
            prep_station=item.prep_station,
            created_by=opened_by,
            quantity=quantity,
            unit_price=item.price,
            status=_order_item_status(order_status, item.prep_station_id),
        )
        _set_timestamp(order_item, created_at=opened_at, updated_at=opened_at)
        if item.prep_station_id:
            prep_stations[item.prep_station_id] = item.prep_station
    return list(prep_stations.values())


def _ticket_status(order_status: str, ticket_index: int) -> str:
    if order_status == Order.Status.READY:
        return KitchenTicket.Status.DONE
    return KitchenTicket.Status.COOKING if ticket_index % 2 == 0 else KitchenTicket.Status.NEW


def _create_active_tickets(restaurant, *, order, prep_stations, opened_at):
    for ticket_index, prep_station in enumerate(prep_stations):
        ticket_status = _ticket_status(order.status, ticket_index)
        completed_at = opened_at + timedelta(minutes=18 + (ticket_index * 4)) if ticket_status == KitchenTicket.Status.DONE else None
        ticket = KitchenTicket.objects.create(
            restaurant=restaurant,
            order=order,
            prep_station=prep_station,
            status=ticket_status,
            routed_via=KitchenTicket.RouteMode.BOTH,
            is_printed=True,
            printed_payload={'provider': 'mock-printer'},
            completed_at=completed_at,
        )
        _set_timestamp(ticket, created_at=opened_at, updated_at=completed_at or opened_at)


def _create_closed_order(
    *,
    restaurant,
    order_number: int,
    channel: str,
    opened_by,
    cashier,
    opened_at,
    closed_at,
    item_entries,
    guest_count: int,
    distribution_point,
    table_session=None,
    note='',
):
    order = Order.objects.create(
        restaurant=restaurant,
        table_session=table_session,
        distribution_point=distribution_point,
        opened_by=opened_by,
        cashier=cashier,
        order_number=order_number,
        channel=channel,
        status=Order.Status.CLOSED,
        guest_count=guest_count,
        note=note,
        closed_at=closed_at,
    )
    _create_order_items(order, opened_by=opened_by, opened_at=opened_at, selected_entries=item_entries, order_status=Order.Status.CLOSED)
    order.recalculate_totals()
    _set_timestamp(order, created_at=opened_at, updated_at=closed_at)
    return order


def _create_active_order(
    *,
    restaurant,
    order_number: int,
    channel: str,
    status: str,
    opened_by,
    opened_at,
    item_entries,
    guest_count: int,
    distribution_point,
    table_session=None,
    note='',
):
    order = Order.objects.create(
        restaurant=restaurant,
        table_session=table_session,
        distribution_point=distribution_point,
        opened_by=opened_by,
        order_number=order_number,
        channel=channel,
        status=status,
        guest_count=guest_count,
        note=note,
    )
    prep_stations = _create_order_items(order, opened_by=opened_by, opened_at=opened_at, selected_entries=item_entries, order_status=status)
    order.recalculate_totals()
    _set_timestamp(order, created_at=opened_at, updated_at=opened_at)
    _create_active_tickets(restaurant, order=order, prep_stations=prep_stations, opened_at=opened_at)
    return order


def seed_orders(
    *,
    restaurant,
    restaurant_spec,
    users_by_username,
    items_by_code,
    halls_by_code,
    tables_by_key,
    cash_desk,
    distribution_points,
):
    history = restaurant_spec.history
    today = timezone.localdate()
    menu_entries = _iter_menu_items(items_by_code)
    available_hall_keys = [
        key for key, table in tables_by_key.items() if table.status == DiningTable.Status.AVAILABLE
    ]
    order_number = history.base_order_number

    for day_index, days_ago in enumerate(range(59, 0, -1), start=1):
        target_date = today - timedelta(days=days_ago)
        shift_opener = users_by_username[history.cashier_usernames[day_index % len(history.cashier_usernames)]]
        shift = _build_shift(
            cash_desk,
            shift_opener,
            opened_at=_at(target_date, 8, 0),
            opening_cash_amount=_opening_cash(day_index),
            note=f'Seeder shift {target_date.isoformat()}',
        )
        totals = {'cash_total': 0, 'card_total': 0, 'qr_total': 0, 'receipt_count': 0}
        closed_orders_for_day = _closed_order_count(history, target_date)

        for order_index in range(closed_orders_for_day):
            channel = history.closed_channel_cycle[(day_index + order_index) % len(history.closed_channel_cycle)]
            opened_by = users_by_username[history.opener_usernames[(day_index + order_index) % len(history.opener_usernames)]]
            cashier = users_by_username[history.cashier_usernames[(day_index + order_index) % len(history.cashier_usernames)]]
            opened_at = _at(target_date, 9 + ((order_index * 3 + day_index) % 8), 10 + ((order_index * 11) % 40))
            closed_at = opened_at + timedelta(minutes=35 + ((order_index + day_index) % 20))
            item_count = history.item_count_cycle[(day_index + order_index) % len(history.item_count_cycle)]
            item_entries = _pick_menu_slice(menu_entries, day_index + (order_index * 2), item_count)
            guest_count = 1 + ((day_index + order_index) % 4)
            distribution_point = distribution_points[_distribution_kind(channel)]
            table_session = None

            if channel == Order.Channel.HALL and available_hall_keys:
                hall_code, table_number = available_hall_keys[(day_index + order_index) % len(available_hall_keys)]
                hall = halls_by_code[hall_code]
                table = tables_by_key[(hall_code, table_number)]
                table_session = _make_closed_table_session(
                    restaurant,
                    hall=hall,
                    table=table,
                    opened_by=opened_by,
                    opened_at=opened_at,
                    closed_at=closed_at,
                    guest_count=guest_count,
                    note=f'{hall.name} historical order',
                )

            order = _create_closed_order(
                restaurant=restaurant,
                order_number=order_number,
                channel=channel,
                opened_by=opened_by,
                cashier=cashier,
                opened_at=opened_at,
                closed_at=closed_at,
                item_entries=item_entries,
                guest_count=guest_count,
                distribution_point=distribution_point,
                table_session=table_session,
                note=f'Demo history {target_date.isoformat()}',
            )

            payment_method = history.payment_method_cycle[(day_index + order_index) % len(history.payment_method_cycle)]
            receipt_ref = f'REC-{restaurant_spec.key}-{order_number}'
            _register_payment(
                order,
                cash_desk=cash_desk,
                shift=shift,
                cashier=cashier,
                method=payment_method,
                closed_at=closed_at,
                receipt_ref=receipt_ref,
            )
            totals[f'{payment_method}_total'] += order.total
            totals['receipt_count'] += 1
            order_number += 1

        _finalize_shift(
            shift,
            totals,
            closed_by=shift_opener,
            closed_at=_at(target_date, 23, 10),
        )

    today_shift_opener = users_by_username[history.cashier_usernames[0]]
    today_shift = _build_shift(
        cash_desk,
        today_shift_opener,
        opened_at=_at(today, 8, 0),
        opening_cash_amount=_opening_cash(0),
        note='Seeder live shift',
    )
    today_totals = {'cash_total': 0, 'card_total': 0, 'qr_total': 0, 'receipt_count': 0}

    for order_index in range(history.today_closed_orders):
        channel = history.closed_channel_cycle[order_index % len(history.closed_channel_cycle)]
        opened_by = users_by_username[history.opener_usernames[order_index % len(history.opener_usernames)]]
        cashier = users_by_username[history.cashier_usernames[order_index % len(history.cashier_usernames)]]
        opened_at = _at(today, 10 + (order_index * 2), 5)
        closed_at = opened_at + timedelta(minutes=40)
        item_count = history.item_count_cycle[order_index % len(history.item_count_cycle)]
        item_entries = _pick_menu_slice(menu_entries, 70 + order_index, item_count)
        guest_count = 1 + (order_index % 4)
        distribution_point = distribution_points[_distribution_kind(channel)]
        table_session = None

        if channel == Order.Channel.HALL and available_hall_keys:
            hall_code, table_number = available_hall_keys[(order_index + 2) % len(available_hall_keys)]
            hall = halls_by_code[hall_code]
            table = tables_by_key[(hall_code, table_number)]
            table_session = _make_closed_table_session(
                restaurant,
                hall=hall,
                table=table,
                opened_by=opened_by,
                opened_at=opened_at,
                closed_at=closed_at,
                guest_count=guest_count,
                note='Today closed hall order',
            )

        order = _create_closed_order(
            restaurant=restaurant,
            order_number=order_number,
            channel=channel,
            opened_by=opened_by,
            cashier=cashier,
            opened_at=opened_at,
            closed_at=closed_at,
            item_entries=item_entries,
            guest_count=guest_count,
            distribution_point=distribution_point,
            table_session=table_session,
            note='Today closed order',
        )
        payment_method = history.payment_method_cycle[order_index % len(history.payment_method_cycle)]
        _register_payment(
            order,
            cash_desk=cash_desk,
            shift=today_shift,
            cashier=cashier,
            method=payment_method,
            closed_at=closed_at,
            receipt_ref=f'REC-{restaurant_spec.key}-{order_number}',
        )
        today_totals[f'{payment_method}_total'] += order.total
        today_totals['receipt_count'] += 1
        order_number += 1

    for active_index in range(history.today_active_orders):
        channel = history.active_channel_cycle[active_index % len(history.active_channel_cycle)]
        status = history.active_status_cycle[active_index % len(history.active_status_cycle)]
        opened_by = users_by_username[history.opener_usernames[active_index % len(history.opener_usernames)]]
        opened_at = _at(today, 15 + active_index, 20)
        item_count = history.item_count_cycle[(active_index + 1) % len(history.item_count_cycle)]
        item_entries = _pick_menu_slice(menu_entries, 100 + active_index, item_count)
        distribution_point = distribution_points[_distribution_kind(channel)]
        guest_count = 2 + (active_index % 3)
        table_session = None

        if channel == Order.Channel.HALL and history.active_hall_table_keys:
            hall_code, table_number = history.active_hall_table_keys[active_index % len(history.active_hall_table_keys)]
            hall = halls_by_code[hall_code]
            table = tables_by_key[(hall_code, table_number)]
            table_session = _make_active_table_session(
                restaurant,
                hall=hall,
                table=table,
                opened_by=opened_by,
                opened_at=opened_at,
                guest_count=guest_count,
                note='Live demo session',
            )

        _create_active_order(
            restaurant=restaurant,
            order_number=order_number,
            channel=channel,
            status=status,
            opened_by=opened_by,
            opened_at=opened_at,
            item_entries=item_entries,
            guest_count=guest_count,
            distribution_point=distribution_point,
            table_session=table_session,
            note='Live demo order',
        )
        order_number += 1

    _finalize_shift(today_shift, today_totals, closed_by=today_shift_opener)
    restaurant.last_order_number = order_number - 1
    restaurant.save(update_fields=['last_order_number', 'updated_at'])


class DistributionPointKind:
    HALL = 'hall'
    TAKEAWAY = 'takeaway'
    DELIVERY = 'delivery'
    ONLINE = 'online'
