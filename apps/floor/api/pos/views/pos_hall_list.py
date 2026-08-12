from django.db.models import Prefetch
from rest_framework import generics, permissions

from apps.floor.api.admin.serializers.active_session_summary import (
    ACTIVE_ORDER_STATUSES,
    PREFETCHED_ACTIVE_ORDERS_ATTR,
    PREFETCHED_SERVICE_TICKETS_ATTR,
)
from apps.floor.api.admin.serializers.dining_table import (
    PREFETCHED_ACTIVE_SESSIONS_ATTR,
)
from apps.floor.api.admin.serializers import HallSerializer
from apps.floor.models import DiningTable, Hall, TableSession
from apps.floor.services import ACTIVE_SESSION_STATUSES
from apps.kitchen.models import KitchenTicket
from apps.platform.services import FeatureGateService
from apps.sales.models import Order
from common.api.permissions import EndpointRBACPermission
from common.api.scopes import get_request_restaurant


class PosHallListView(generics.ListAPIView):
    serializer_class = HallSerializer
    permission_classes = [permissions.IsAuthenticated, EndpointRBACPermission]
    feature_gate_service_class = FeatureGateService

    def get_queryset(self):
        restaurant = get_request_restaurant(self.request)
        self.feature_gate_service_class().ensure_hall_access(restaurant=restaurant)

        service_tickets = KitchenTicket.objects.filter(
            status__in=(KitchenTicket.Status.NEW, KitchenTicket.Status.COOKING),
        )
        active_orders = (
            Order.objects.filter(status__in=ACTIVE_ORDER_STATUSES)
            .prefetch_related(
                Prefetch(
                    'kitchen_tickets',
                    queryset=service_tickets,
                    to_attr=PREFETCHED_SERVICE_TICKETS_ATTR,
                )
            )
            .order_by('-created_at')
        )
        active_sessions = (
            TableSession.objects.filter(status__in=ACTIVE_SESSION_STATUSES)
            .prefetch_related(
                Prefetch(
                    'orders',
                    queryset=active_orders,
                    to_attr=PREFETCHED_ACTIVE_ORDERS_ATTR,
                )
            )
            .order_by('-created_at')
        )
        tables = (
            DiningTable.objects.select_related('zone')
            .prefetch_related(
                Prefetch(
                    'table_sessions',
                    queryset=active_sessions,
                    to_attr=PREFETCHED_ACTIVE_SESSIONS_ATTR,
                )
            )
            .order_by('table_number', 'name')
        )
        return (
            Hall.objects.filter(zone_or_cabin__restaurant=restaurant, is_active=True)
            .select_related('zone_or_cabin', 'zone_or_cabin__restaurant')
            .prefetch_related(Prefetch('tables', queryset=tables))
            .order_by('sort_order', 'name')
        )
