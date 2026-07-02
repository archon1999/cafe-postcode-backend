from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from decimal import Decimal, ROUND_HALF_UP

from apps.billing.helpers import get_receipt_model
from apps.integrations.services import build_order_label, print_prebill
from apps.sales.helpers import get_order_model
from apps.sales.models import OrderItem

Receipt = get_receipt_model()
Order = get_order_model()


class OrderPrebillService:
    @staticmethod
    def _money(value) -> int:
        return int(value or 0)

    @staticmethod
    def _vat_amount(*, amount: int, percent) -> int:
        try:
            rate = Decimal(str(percent or 0))
        except Exception:
            return 0
        if amount <= 0 or rate <= 0:
            return 0
        included_vat = Decimal(amount) * rate / (Decimal('100') + rate)
        return int(included_vat.quantize(Decimal('1'), rounding=ROUND_HALF_UP))

    def ensure_printable(self, *, order: Order):
        if order.status in {Order.Status.CLOSED, Order.Status.CANCELLED}:
            raise ValidationError({'detail': 'Closed or cancelled orders cannot be printed as prebill.'})
        if not order.items.exists():
            raise ValidationError({'detail': 'Order has no items.'})

    def build_snapshot(self, *, order: Order) -> dict:
        active_items = order.items.exclude(status=OrderItem.Status.CANCELLED).select_related('catalog_item')
        printed_at = timezone.localtime(timezone.now())
        table_label = None
        if order.table_session_id and order.table_session and order.table_session.table:
            table_label = f"Stol: {order.table_session.table.name}"

        vat_enabled = bool(getattr(order.restaurant, 'vat_enabled', False))
        vat_percent = getattr(order.restaurant, 'vat_percent', 0) or 0
        total = self._money(order.total)

        return {
            'restaurant_name': order.restaurant.name,
            'restaurant_legal_name': order.restaurant.legal_name,
            'restaurant_address': order.restaurant.address,
            'restaurant_phone': order.restaurant.phone,
            'restaurant_social': order.restaurant.social,
            'tax_number': order.restaurant.tax_number,
            'order_id': str(order.id),
            'order_number': order.order_number,
            'order_label': build_order_label(order),
            'channel': order.channel,
            'channel_label': self._channel_label(order),
            'table_label': table_label,
            'waiter_name': order.opened_by.full_name if order.opened_by_id and order.opened_by else '',
            'printed_at_label': printed_at.strftime('%Y-%m-%d %H:%M:%S'),
            'items': [
                {
                    'name': item.catalog_item.name,
                    'quantity': int(item.quantity or 0),
                    'line_total': self._money(item.line_total),
                    'note': item.note or '',
                }
                for item in active_items
            ],
            'subtotal': self._money(order.subtotal),
            'service_fee': max(total - self._money(order.subtotal), 0),
            'vat_enabled': vat_enabled,
            'vat_percent': str(vat_percent),
            'vat_amount': self._vat_amount(amount=total, percent=vat_percent) if vat_enabled else 0,
            'total': total,
            'order_note': order.note or '',
        }

    @staticmethod
    def _channel_label(order: Order) -> str:
        if order.channel == Order.Channel.HALL:
            return 'Zalda'
        if order.channel == Order.Channel.DELIVERY:
            return 'Yetkazib berish'
        if order.channel == Order.Channel.ONLINE:
            return 'Online'
        return 'Olib ketish'

    @transaction.atomic
    def print(self, *, order: Order, cash_desk=None):
        self.ensure_printable(order=order)
        snapshot = self.build_snapshot(order=order)

        try:
            result = print_prebill(order=order, payload=snapshot, cash_desk=cash_desk)
        except ValueError as error:
            raise ValidationError({'detail': str(error)}) from error

        if result.get('requires_client_print'):
            status = Receipt.Status.CREATED
        elif result.get('ok'):
            status = Receipt.Status.SENT
        else:
            status = Receipt.Status.FAILED

        receipt = Receipt.objects.create(
            order=order,
            kind=Receipt.Kind.PREBILL,
            status=status,
            provider=result.get('provider', ''),
            payload={
                'snapshot': snapshot,
                'result': result,
            },
        )
        return {'receipt': receipt, 'result': result}

    @transaction.atomic
    def record_print_result(self, *, receipt: Receipt, result: dict):
        if receipt.kind != Receipt.Kind.PREBILL:
            raise ValidationError({'detail': 'Only prebill receipts can be updated from this endpoint.'})

        payload = dict(receipt.payload or {})
        original_result = dict(payload.get('result') or {})
        client_result = dict(result or {})
        ok = bool(client_result.get('ok'))

        payload['client_result'] = client_result
        payload['result'] = {
            **original_result,
            **client_result,
            'ok': ok,
            'requires_client_print': False,
            'client_reported_at': timezone.now().isoformat(),
        }

        receipt.status = Receipt.Status.SENT if ok else Receipt.Status.FAILED
        receipt.payload = payload
        receipt.save()
        return receipt
