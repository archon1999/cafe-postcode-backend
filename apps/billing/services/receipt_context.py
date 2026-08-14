from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.integrations.services import build_order_label
from apps.sales.helpers import get_order_model

Order = get_order_model()


def build_receipt_payload(*, order, receipt_result: dict) -> dict:
    payload = dict(receipt_result or {})
    payload['order_number'] = order.order_number
    payload['order_label'] = build_order_label(order)
    payload['channel_label'] = order_channel_label(order)
    payload['restaurant_name'] = order.restaurant.name
    payload['restaurant_legal_name'] = order.restaurant.legal_name or order.restaurant.name
    payload['restaurant_address'] = order.restaurant.address
    payload['restaurant_phone'] = order.restaurant.phone
    payload['restaurant_social'] = getattr(order.restaurant, 'social', '')
    payload['service_fee_percent'] = str(order.service_fee_percent)
    payload['service_fee_components'] = order.get_service_fee_components()
    payload['table_label'] = order_table_label(order)
    payload['cashier_name'] = order.cashier.full_name if order.cashier_id and order.cashier else ''
    payload['cashier_id'] = str(order.cashier_id or '')
    payload['waiter_name'] = order.opened_by.full_name if order.opened_by_id and order.opened_by else ''
    payload['order_note'] = order.note or ''
    if order.channel == Order.Channel.DELIVERY:
        payload['delivery_phone'] = order.delivery_phone or ''
        payload['delivery_address'] = order.delivery_address or ''
    return payload


def order_channel_label(order) -> str:
    labels = {
        Order.Channel.HALL: 'Zal',
        Order.Channel.TAKEAWAY: 'Soboy',
        Order.Channel.DELIVERY: 'Dostavka',
        Order.Channel.ONLINE: 'Online',
    }
    return labels.get(order.channel, str(order.channel or ''))


def order_table_label(order) -> str:
    if not order.table_session_id or not order.table_session:
        return ''
    table = getattr(order.table_session, 'table', None)
    return f"Stol: {table.name}" if table is not None else ''


def parse_payload_datetime(value):
    if not value:
        return None
    parsed = parse_datetime(str(value))
    if parsed is None:
        return None
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
    return parsed
