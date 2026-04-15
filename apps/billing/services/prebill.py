from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.billing.helpers import get_receipt_model
from apps.integrations.services import print_prebill
from apps.sales.helpers import get_order_model
from apps.sales.models import OrderItem

Receipt = get_receipt_model()
Order = get_order_model()


class OrderPrebillService:
    @staticmethod
    def _money(value) -> int:
        return int(value or 0)

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

        return {
            'restaurant_name': order.restaurant.name,
            'order_id': str(order.id),
            'order_number': order.order_number,
            'channel': order.channel,
            'channel_label': 'Zalda' if order.channel == Order.Channel.HALL else 'Olib ketish',
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
            'service_fee': max(self._money(order.total) - self._money(order.subtotal), 0),
            'total': self._money(order.total),
            'order_note': order.note or '',
        }

    @transaction.atomic
    def print(self, *, order: Order):
        self.ensure_printable(order=order)
        snapshot = self.build_snapshot(order=order)

        try:
            result = print_prebill(order=order, payload=snapshot)
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
