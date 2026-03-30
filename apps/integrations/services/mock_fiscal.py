from django.utils import timezone

from apps.integrations.models import IntegrationConfig

from .config_resolver import IntegrationConfigResolverService


class MockFiscalIntegrationService:
    resolver_service_class = IntegrationConfigResolverService

    def issue_receipt(self, order, payment):
        config = self.resolver_service_class().get_config(
            kind=IntegrationConfig.Kind.FISCAL,
            restaurant=order.restaurant,
            branch=order.branch,
        )
        return {
            'ok': True,
            'provider': config.provider if config else 'mock-fiscal',
            'receipt_number': f'RCPT-{order.order_number}',
            'mode': config.mode if config else IntegrationConfig.Mode.MOCK,
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
