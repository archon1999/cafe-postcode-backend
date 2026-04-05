from apps.sales.helpers import get_order_model

from .state import OrderStateService

Order = get_order_model()


class OrderSubmissionService:
    state_service_class = OrderStateService

    def submit(self, order: Order):
        return self.state_service_class().submit_order(order=order)
