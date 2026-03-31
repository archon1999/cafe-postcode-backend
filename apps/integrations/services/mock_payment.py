from django.utils import timezone

from apps.integrations.models import IntegrationConfig

from .config_resolver import IntegrationConfigResolverService


class MockPaymentIntegrationService:
    resolver_service_class = IntegrationConfigResolverService

    def charge_payment(self, order, payment):
        config = self.resolver_service_class().get_config(
            kind=IntegrationConfig.Kind.PAYMENT,
            restaurant=order.restaurant,
        )
        qr_payload = {
            'label': f'QR-{order.order_number}',
            'content': f'mock://payment/order/{order.id}/amount/{payment.amount}',
            'expires_in_seconds': 5,
        }
        return {
            'ok': True,
            'provider': config.provider if config else 'mock-payment',
            'reference': f'PAY-{payment.id}',
            'mode': config.mode if config else IntegrationConfig.Mode.MOCK,
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
