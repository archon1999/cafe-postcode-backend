from datetime import timedelta

from django.db.models import Q
from django.utils import timezone
from rest_framework import generics, permissions

from apps.kitchen.api.pos.serializers import KitchenTicketSerializer
from apps.kitchen.models import KitchenTicket
from apps.kitchen.services import complete_stale_closed_order_kitchen_work
from apps.platform.services import FeatureGateService
from apps.sales.models import Order
from common.api.permissions import (
    EndpointRBACPermission,
    POS_KITCHEN_ORDERS_VIEW_ALL_PERMISSION,
    has_permission_code,
)
from common.api.scopes import get_request_restaurant


class KitchenQueueView(generics.ListAPIView):
    serializer_class = KitchenTicketSerializer
    permission_classes = [permissions.IsAuthenticated, EndpointRBACPermission]
    feature_gate_service_class = FeatureGateService

    def get_queryset(self):
        restaurant = get_request_restaurant(self.request)
        self.feature_gate_service_class().ensure_kitchen_access(restaurant=restaurant)
        complete_stale_closed_order_kitchen_work(restaurant=restaurant)

        queryset = KitchenTicket.objects.filter(restaurant=restaurant).select_related(
            'prep_station',
            'order__opened_by',
            'order__table_session__hall',
            'order__table_session__table',
        ).prefetch_related('order__items__catalog_item', 'order__items__prep_station', 'order__kitchen_tickets')
        prep_station_id = self.request.query_params.get('prep_station_id')
        if prep_station_id:
            queryset = queryset.filter(prep_station_id=prep_station_id)
        status_value = self.request.query_params.get('status')
        if status_value:
            queryset = queryset.filter(status=status_value)
        else:
            cutoff = timezone.now() - timedelta(days=1)
            active_order_statuses = [Order.Status.OPEN, Order.Status.SUBMITTED, Order.Status.READY]
            queryset = queryset.filter(
                Q(
                    status__in=(KitchenTicket.Status.NEW, KitchenTicket.Status.COOKING),
                    order__status__in=active_order_statuses,
                )
                | Q(
                    status__in=(KitchenTicket.Status.NEW, KitchenTicket.Status.COOKING),
                    created_at__gte=cutoff,
                )
                | (
                    Q(status=KitchenTicket.Status.DONE, completed_at__gte=cutoff)
                    & (~Q(order__status=Order.Status.CLOSED) | Q(order__closed_at__gte=cutoff))
                )
            )
        if not has_permission_code(self.request.user, POS_KITCHEN_ORDERS_VIEW_ALL_PERMISSION):
            queryset = queryset.filter(Q(prep_station__cooks=self.request.user) | Q(prep_station__cooks__isnull=True))
        return queryset.distinct()
