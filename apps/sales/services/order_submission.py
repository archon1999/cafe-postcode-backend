from apps.sales.helpers import get_order_model

from .marking import validate_order_markings
from .state import OrderStateService

Order = get_order_model()


class OrderSubmissionService:
    state_service_class = OrderStateService

    def submit(self, order: Order):
        validate_order_markings(order)
        return self.state_service_class().submit_order(order=order)
