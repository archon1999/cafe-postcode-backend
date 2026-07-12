import hashlib
import json
from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.printing.models import PrintDocument, PrintTemplate

from .templates import ensure_restaurant_templates


def _money(value) -> int:
    return int(value or 0)


def _json_number(value) -> int | float:
    number = Decimal(str(value or 0))
    return int(number) if number == number.to_integral_value() else float(number)


def _included_vat(*, amount: int, percent) -> int:
    rate = Decimal(str(percent or 0))
    if amount <= 0 or rate <= 0:
        return 0
    value = Decimal(amount) * rate / (Decimal('100') + rate)
    return int(value.quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def _channel_label(order) -> str:
    labels = {
        'hall': 'Зал',
        'takeaway': 'С собой',
        'delivery': 'Доставка',
        'online': 'Online',
    }
    return labels.get(str(order.channel or ''), str(order.channel or ''))


def _table_parts(order) -> tuple[str, str]:
    session = getattr(order, 'table_session', None)
    table = getattr(session, 'table', None) if session is not None else None
    hall = getattr(session, 'hall', None) if session is not None else None
    return (str(getattr(table, 'name', '') or ''), str(getattr(hall, 'name', '') or ''))


def _payment_method(*, cash_amount: int, card_amount: int, fallback: str) -> str:
    if cash_amount > 0 and card_amount > 0:
        return 'mixed'
    if card_amount > 0:
        return 'card'
    if cash_amount > 0:
        return 'cash'
    return fallback


def build_payment_print_snapshot(*, receipt, fiscal_result: dict | None = None) -> dict:
    order = receipt.order
    payment = receipt.payment
    restaurant = order.restaurant
    table_name, hall_name = _table_parts(order)
    active_items = order.items.exclude(status=order.items.model.Status.CANCELLED).select_related('catalog_item')
    paid = order.payments.filter(status=payment.Status.SUCCEEDED).aggregate(
        amount=Sum('amount'),
        cash=Sum('cash_amount'),
        card=Sum('card_amount'),
    )
    amount = _money(paid.get('amount'))
    cash_amount = _money(paid.get('cash'))
    card_amount = _money(paid.get('card'))
    total = _money(order.total)
    subtotal = _money(order.subtotal)
    vat_enabled = bool(getattr(restaurant, 'vat_enabled', False))
    vat_percent = getattr(restaurant, 'vat_percent', 0) or 0
    result = dict(fiscal_result or receipt.payload or {})
    response = result.get('response') if isinstance(result.get('response'), dict) else {}

    return {
        'restaurant': {
            'name': restaurant.name,
            'legalName': restaurant.legal_name or restaurant.name,
            'address': restaurant.address,
            'phone': restaurant.phone,
            'social': getattr(restaurant, 'social', ''),
            'taxNumber': restaurant.tax_number,
        },
        'order': {
            'id': str(order.id),
            'displayNumber': str(order.display_name or order.order_number),
            'channel': order.channel,
            'channelLabel': _channel_label(order),
            'table': table_name,
            'hall': hall_name,
            'guestCount': int(order.guest_count or 0),
            'openedAt': timezone.localtime(order.created_at).isoformat(),
            'waiter': order.opened_by.full_name if order.opened_by_id and order.opened_by else '',
            'cashier': order.cashier.full_name if order.cashier_id and order.cashier else '',
            'note': order.note or '',
            'deliveryPhone': order.delivery_phone or '',
            'deliveryAddress': order.delivery_address or '',
        },
        'items': [
            {
                'name': item.catalog_item.name if item.catalog_item_id else item.name_snapshot,
                'quantity': int(item.quantity or 0),
                'unitPrice': _money(item.unit_price),
                'lineTotal': _money(item.line_total),
                'vat': _included_vat(amount=_money(item.line_total), percent=vat_percent) if vat_enabled else 0,
                'vatPercent': _json_number(vat_percent),
                'note': item.note or '',
            }
            for item in active_items
        ],
        'payment': {
            'id': str(payment.id),
            'method': _payment_method(cash_amount=cash_amount, card_amount=card_amount, fallback=payment.method),
            'amount': amount,
            'cash': cash_amount,
            'card': card_amount,
            'change': 0,
            'paidAt': timezone.localtime(payment.paid_at).isoformat() if payment.paid_at else '',
            'operationType': 'sale',
        },
        'totals': {
            'subtotal': subtotal,
            'serviceFee': max(total - subtotal, 0),
            'serviceFeePercent': _json_number(getattr(restaurant, 'service_fee_percent', 0)),
            'vat': _included_vat(amount=total, percent=vat_percent) if vat_enabled else 0,
            'vatPercent': _json_number(vat_percent),
            'total': total,
        },
        'fiscal': {
            'receiptNumber': str(
                result.get('receipt_number')
                or result.get('receiptNumber')
                or response.get('ReceiptNumber')
                or ''
            ),
            'terminalId': str(result.get('terminal_id') or result.get('terminalId') or response.get('TerminalID') or ''),
            'factoryId': str(result.get('factory_id') or result.get('factoryId') or response.get('FactoryID') or ''),
            'fiscalSign': str(result.get('fiscal_sign') or result.get('fiscalSign') or response.get('FiscalSign') or ''),
            'qrUrl': str(result.get('qr_code_url') or result.get('qrCodeUrl') or response.get('QRCodeURL') or ''),
            'registeredAt': receipt.fiscal_registered_at.isoformat() if receipt.fiscal_registered_at else '',
        },
        'system': {'copyNumber': 1, 'isReprint': False},
    }


def build_legacy_receipt_payload(*, snapshot: dict, fiscal_result: dict | None = None) -> dict:
    restaurant = snapshot['restaurant']
    order = snapshot['order']
    payment = snapshot['payment']
    totals = snapshot['totals']
    payload = dict(fiscal_result or {})
    payload.update(
        {
            'restaurant_name': restaurant['name'],
            'restaurant_legal_name': restaurant['legalName'],
            'restaurant_address': restaurant['address'],
            'restaurant_phone': restaurant['phone'],
            'restaurant_social': restaurant['social'],
            'tax_number': restaurant['taxNumber'],
            'order_id': order['id'],
            'order_number': order['displayNumber'],
            'order_label': f"#{order['displayNumber']}",
            'channel': order['channel'],
            'channel_label': order['channelLabel'],
            'table_label': f"Stol: {order['table']}" if order['table'] else '',
            'waiter_name': order['waiter'],
            'cashier_name': order['cashier'],
            'order_note': order['note'],
            'items': [
                {
                    'name': item['name'],
                    'quantity': item['quantity'],
                    'unit_price': item['unitPrice'],
                    'line_total': item['lineTotal'],
                    'note': item['note'],
                }
                for item in snapshot['items']
            ],
            'subtotal': totals['subtotal'],
            'service_fee': totals['serviceFee'],
            'vat_amount': totals['vat'],
            'total': totals['total'],
            'payment_method': payment['method'],
            'amount': payment['amount'],
            'cash_amount': payment['cash'],
            'card_amount': payment['card'],
            'change': payment['change'],
            'paid_at': payment['paidAt'],
        }
    )
    return payload


def build_kitchen_print_snapshot(*, ticket) -> dict:
    order = ticket.order
    restaurant = ticket.restaurant
    table_name, hall_name = _table_parts(order)
    aggregated_items = {}
    queryset = (
        order.items.filter(prep_station=ticket.prep_station)
        .exclude(status=order.items.model.Status.CANCELLED)
        .select_related('catalog_item')
        .order_by('created_at')
    )
    for item in queryset:
        name = item.catalog_item.name if item.catalog_item_id else ''
        key = (name, item.note or '')
        current = aggregated_items.setdefault(
            key,
            {'name': name, 'quantity': 0, 'unitPrice': _money(item.unit_price), 'lineTotal': 0, 'note': item.note or ''},
        )
        current['quantity'] += int(item.quantity or 0)
        current['lineTotal'] += _money(item.line_total)

    items = list(aggregated_items.values())
    return {
        'restaurant': {
            'name': restaurant.name,
            'legalName': restaurant.legal_name or restaurant.name,
            'address': restaurant.address,
            'phone': restaurant.phone,
            'social': getattr(restaurant, 'social', ''),
            'taxNumber': restaurant.tax_number,
        },
        'order': {
            'id': str(order.id),
            'displayNumber': str(order.display_name or order.order_number),
            'channel': order.channel,
            'channelLabel': _channel_label(order),
            'table': table_name,
            'hall': hall_name,
            'guestCount': int(order.guest_count or 0),
            'openedAt': timezone.localtime(order.created_at).isoformat(),
            'waiter': order.opened_by.full_name if order.opened_by_id and order.opened_by else '',
            'cashier': order.cashier.full_name if order.cashier_id and order.cashier else '',
            'note': order.note or '',
            'deliveryPhone': order.delivery_phone or '',
            'deliveryAddress': order.delivery_address or '',
        },
        'items': items,
        'totals': {'total': sum(_money(item['lineTotal']) for item in items)},
        'kitchen': {
            'ticketNumber': f'K-{str(ticket.id)[-6:].upper()}',
            'prepStation': ticket.prep_station.name,
            'createdAt': timezone.localtime(ticket.created_at).isoformat(),
        },
        'system': {'copyNumber': 1, 'isReprint': False},
    }


def _hash_document(*, snapshot: dict, template_version_id) -> str:
    canonical = json.dumps(
        {'snapshot': snapshot, 'templateVersionId': str(template_version_id)},
        ensure_ascii=False,
        sort_keys=True,
        separators=(',', ':'),
    )
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()


@transaction.atomic
def create_receipt_print_document(*, receipt, fiscal_result: dict | None = None, created_by=None):
    kind_map = {
        'plain': PrintTemplate.Kind.PAYMENT_RECEIPT_PLAIN,
        'fiscal': PrintTemplate.Kind.PAYMENT_RECEIPT_FISCAL,
        'refund': PrintTemplate.Kind.PAYMENT_RECEIPT_FISCAL if receipt.fiscal_registered_at else PrintTemplate.Kind.PAYMENT_RECEIPT_PLAIN,
    }
    kind = kind_map[receipt.kind]
    ensure_restaurant_templates(restaurant=receipt.order.restaurant)
    template = PrintTemplate.objects.select_related('published_version').get(
        restaurant=receipt.order.restaurant,
        kind=kind,
    )
    snapshot = build_payment_print_snapshot(receipt=receipt, fiscal_result=fiscal_result)
    content_hash = _hash_document(snapshot=snapshot, template_version_id=template.published_version_id)
    document, created = PrintDocument.objects.get_or_create(
        restaurant=receipt.order.restaurant,
        idempotency_key=f'receipt:{receipt.id}',
        defaults={
            'kind': kind,
            'operation_type': PrintDocument.OperationType.REFUND if receipt.kind == 'refund' else PrintDocument.OperationType.SALE,
            'source_model': 'billing.receipt',
            'source_id': receipt.id,
            'data_snapshot': snapshot,
            'template_version': template.published_version,
            'content_hash': content_hash,
            'metadata': {
                'cashDeskId': str(receipt.payment.cash_desk_id)
                if receipt.payment_id and receipt.payment.cash_desk_id
                else None,
            },
            'created_by': created_by,
        },
    )
    if not created and document.content_hash != content_hash:
        raise ValueError('Print document idempotency key already exists with different content.')
    return document, snapshot


def attach_receipt_print_document(*, receipt, fiscal_result: dict | None = None, created_by=None):
    """Create the immutable document once and persist its reference on the receipt."""
    if receipt.print_document_id:
        return receipt.print_document

    document, snapshot = create_receipt_print_document(
        receipt=receipt,
        fiscal_result=fiscal_result,
        created_by=created_by,
    )
    payload = dict(receipt.payload or {})
    if receipt.kind == 'plain' and not payload:
        payload = build_legacy_receipt_payload(snapshot=snapshot)
    payload['print_document_id'] = str(document.id)
    receipt.print_document = document
    receipt.payload = payload
    receipt.save(update_fields=['print_document', 'payload', 'updated_at'])
    return document


@transaction.atomic
def create_kitchen_ticket_print_document(*, ticket, created_by=None):
    ticket = type(ticket).objects.select_for_update().select_related('restaurant', 'order', 'prep_station').get(pk=ticket.pk)
    ensure_restaurant_templates(restaurant=ticket.restaurant)
    template = PrintTemplate.objects.select_related('published_version').get(
        restaurant=ticket.restaurant,
        kind=PrintTemplate.Kind.KITCHEN_TICKET,
    )
    snapshot = build_kitchen_print_snapshot(ticket=ticket)
    content_hash = _hash_document(snapshot=snapshot, template_version_id=template.published_version_id)
    existing = (
        PrintDocument.objects.filter(
            restaurant=ticket.restaurant,
            source_model='kitchen.kitchenticket',
            source_id=ticket.id,
            content_hash=content_hash,
        )
        .order_by('-created_at')
        .first()
    )
    if existing is not None:
        return existing, snapshot

    revision = (
        PrintDocument.objects.filter(
            restaurant=ticket.restaurant,
            source_model='kitchen.kitchenticket',
            source_id=ticket.id,
        ).count()
        + 1
    )
    document, created = PrintDocument.objects.get_or_create(
        restaurant=ticket.restaurant,
        idempotency_key=f'kitchen-ticket:{ticket.id}:v{revision}',
        defaults={
            'kind': PrintTemplate.Kind.KITCHEN_TICKET,
            'operation_type': PrintDocument.OperationType.SALE,
            'source_model': 'kitchen.kitchenticket',
            'source_id': ticket.id,
            'data_snapshot': snapshot,
            'template_version': template.published_version,
            'content_hash': content_hash,
            'metadata': {
                'prepStationId': str(ticket.prep_station_id),
                'revision': revision,
            },
            'created_by': created_by,
        },
    )
    if not created and document.content_hash != content_hash:
        raise ValueError('Kitchen print document idempotency key already exists with different content.')
    return document, snapshot
