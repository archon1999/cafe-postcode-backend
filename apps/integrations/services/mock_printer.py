from django.utils import timezone


class MockPrinterIntegrationService:
    def __init__(self, config=None):
        self.config = config

    def _get_config(self, restaurant):
        return self.config

    def print_ticket(self, ticket):
        config = self._get_config(ticket.restaurant)
        return {
            'ok': True,
            'provider': config.provider if config else 'mock-printer',
            'ticket_id': str(ticket.id),
            'printed_at': timezone.now().isoformat(),
        }

    def print_prebill(self, order, payload):
        config = self._get_config(order.restaurant)
        return {
            'ok': True,
            'provider': config.provider if config else 'mock-printer',
            'printed_at': timezone.now().isoformat(),
            'order_id': str(order.id),
            'order_number': order.order_number,
            'snapshot': payload,
        }
