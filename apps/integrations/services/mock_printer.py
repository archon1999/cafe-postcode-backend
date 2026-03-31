from django.utils import timezone

from apps.integrations.models import IntegrationConfig

from .config_resolver import IntegrationConfigResolverService


class MockPrinterIntegrationService:
    resolver_service_class = IntegrationConfigResolverService

    def print_ticket(self, ticket):
        config = self.resolver_service_class().get_config(
            kind=IntegrationConfig.Kind.PRINTER,
            restaurant=ticket.restaurant,
        )
        return {
            'ok': True,
            'provider': config.provider if config else 'mock-printer',
            'ticket_id': str(ticket.id),
            'mode': config.mode if config else IntegrationConfig.Mode.MOCK,
            'printed_at': timezone.now().isoformat(),
        }
