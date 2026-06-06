from django.utils import timezone


class MockPaymentIntegrationService:
    def __init__(self, config=None):
        self.config = config

    def charge_payment(self, order, payment):
        config = self.config
        if config is not None and config.provider != 'mock-payment':
            config = None
        qr_payload = {
            'label': f'QR-{order.order_number}',
            'content': f'mock://payment/order/{order.id}/amount/{payment.amount}',
            'expires_in_seconds': 5,
        }
        return {
            'ok': True,
            'provider': config.provider if config else 'mock-payment',
            'reference': f'PAY-{payment.id}',
            'method': payment.method,
            'qr': qr_payload if payment.method == payment.Method.QR else None,
            'processed_at': timezone.now().isoformat(),
        }

    def refund_payment(self, payment, reason=''):
        return {
            'ok': True,
            'provider': 'mock-payment',
            'reference': f'RFND-{payment.id}',
            'method': payment.method,
            'reason': reason or '',
            'processed_at': timezone.now().isoformat(),
        }
