from django.db.models import Prefetch

from rest_framework import generics, permissions

from apps.floor.models import DiningTable, Hall, TableSession
from apps.floor.serializers import HallSerializer
from apps.kitchen.models import KitchenTicket
from apps.orders.models import Order
from apps.organizations.services import FeatureGateService
from common.api.permissions import HasPermissionCode
from common.api.scopes import get_request_branch


class PosHallListView(generics.ListAPIView):
    serializer_class = HallSerializer
    permission_classes = [permissions.IsAuthenticated, HasPermissionCode]
    permission_code = 'hall.view'
    feature_gate_service_class = FeatureGateService

    def get_queryset(self):
        branch = get_request_branch(self.request)
        self.feature_gate_service_class().ensure_hall_access(restaurant=branch.restaurant)
        order_queryset = (
            Order.objects.exclude(status__in=[Order.Status.CLOSED, Order.Status.CANCELLED])
            .prefetch_related(Prefetch('kitchen_tickets', queryset=KitchenTicket.objects.order_by('-created_at')))
            .order_by('-created_at')
        )
        table_session_queryset = (
            TableSession.objects.filter(status__in=[TableSession.Status.OPEN, TableSession.Status.PENDING_PAYMENT])
            .select_related('assigned_waiter')
            .prefetch_related(Prefetch('orders', queryset=order_queryset))
            .order_by('-created_at')
        )
        table_queryset = (
            DiningTable.objects.filter(is_active=True)
            .prefetch_related(Prefetch('table_sessions', queryset=table_session_queryset))
            .order_by('table_number', 'name')
        )

        return Hall.objects.filter(branch=branch, is_active=True).prefetch_related(Prefetch('tables', queryset=table_queryset)).order_by(
            'level',
            'sort_order',
            'name',
        )
