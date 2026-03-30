from apps.orders.models import Order
from apps.orders.services.state import OrderStateService


class OrderSubmissionService:
    state_service_class = OrderStateService

    def submit(self, order: Order):
        return self.state_service_class().submit_order(order=order)
