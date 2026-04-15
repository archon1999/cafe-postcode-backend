from django.utils import timezone

from apps.integrations.models import IntegrationConfig

from .config_resolver import IntegrationConfigResolverService


class MockPrinterIntegrationService:
    resolver_service_class = IntegrationConfigResolverService

    def __init__(self, config=None):
        self.config = config

    def _get_config(self, restaurant):
        return self.config or self.resolver_service_class().get_config(
            kind=IntegrationConfig.Kind.PRINTER,
            restaurant=restaurant,
        )

    def print_ticket(self, ticket):
        config = self._get_config(ticket.restaurant)
        return {
            'ok': True,
            'provider': config.provider if config else 'mock-printer',
            'ticket_id': str(ticket.id),
            'mode': config.mode if config else IntegrationConfig.Mode.MOCK,
            'printed_at': timezone.now().isoformat(),
        }

    def print_prebill(self, order, payload):
        config = self._get_config(order.restaurant)
        return {
            'ok': True,
            'provider': config.provider if config else 'mock-printer',
            'mode': config.mode if config else IntegrationConfig.Mode.MOCK,
            'printed_at': timezone.now().isoformat(),
            'order_id': str(order.id),
            'order_number': order.order_number,
            'snapshot': payload,
        }
