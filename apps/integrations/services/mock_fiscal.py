from django.utils import timezone


class MockFiscalIntegrationService:
    def issue_receipt(self, order, payment):
        return {
            'ok': True,
            'provider': 'mock-fiscal',
            'receipt_number': f'RCPT-{order.order_number}',
            'issued_at': timezone.now().isoformat(),
        }

    def reprint_receipt(self, receipt):
        return {
            'ok': True,
            'provider': receipt.provider or 'mock-fiscal',
            'receipt_number': receipt.payload.get('receipt_number', f'RCPT-{receipt.order.order_number}'),
            'reprinted_at': timezone.now().isoformat(),
        }

    def issue_refund_receipt(self, order, payment, refund):
        return {
            'ok': True,
            'provider': 'mock-fiscal',
            'receipt_number': f'RFND-RCPT-{order.order_number}',
            'payment_id': str(payment.id),
            'refund_id': str(refund.id),
            'issued_at': timezone.now().isoformat(),
        }
