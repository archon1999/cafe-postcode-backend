from rest_framework import generics, permissions

from apps.orders.models import Order
from apps.orders.serializers import OrderSerializer
from apps.organizations.services import FeatureGateService
from common.api.permissions import EndpointRBACPermission
from common.api.scopes import get_request_restaurant
from common.utils.date import tashkent_day_bounds


class OpenCheckListView(generics.ListAPIView):
    serializer_class = OrderSerializer
    permission_classes = [permissions.IsAuthenticated, EndpointRBACPermission]
    pagination_class = None
    feature_gate_service_class = FeatureGateService

    def get_queryset(self):
        restaurant = get_request_restaurant(self.request)
        self.feature_gate_service_class().ensure_cashier_access(restaurant=restaurant)
        status_filter = self.request.query_params.get('status', 'open')
        queryset = (
            Order.objects.filter(restaurant=restaurant)
            .select_related(
                'table_session',
                'table_session__hall',
                'table_session__table',
                'opened_by',
                'cashier',
            )
            .prefetch_related('items__catalog_item', 'items__prep_station', 'payments', 'receipts')
        )
        if status_filter == 'closed':
            start, end = tashkent_day_bounds()
            return queryset.filter(status=Order.Status.CLOSED, closed_at__gte=start, closed_at__lt=end)

        return queryset.filter(status__in=[Order.Status.SUBMITTED, Order.Status.READY])
