from rest_framework import generics, permissions

from apps.orders.models import Order
from apps.orders.serializers import OrderSerializer
from common.api.permissions import HasPermissionCode
from common.api.scopes import get_request_branch


class PosOrderDetailView(generics.RetrieveUpdateAPIView):
    serializer_class = OrderSerializer
    permission_classes = [permissions.IsAuthenticated, HasPermissionCode]
    permission_code = 'orders.view'

    def get_queryset(self):
        branch = get_request_branch(self.request)
        return Order.objects.filter(branch=branch).select_related(
            'table_session',
            'table_session__hall',
            'table_session__table',
            'opened_by',
            'cashier',
        ).prefetch_related(
            'items__catalog_item',
            'items__prep_station',
            'payments',
            'receipts',
        )
