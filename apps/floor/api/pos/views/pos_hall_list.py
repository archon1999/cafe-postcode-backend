from rest_framework import generics, permissions

from apps.floor.models import Hall
from apps.floor.api.admin.serializers import HallSerializer
from apps.platform.services import FeatureGateService
from common.api.permissions import EndpointRBACPermission
from common.api.scopes import get_request_restaurant


class PosHallListView(generics.ListAPIView):
    serializer_class = HallSerializer
    permission_classes = [permissions.IsAuthenticated, EndpointRBACPermission]
    feature_gate_service_class = FeatureGateService

    def get_queryset(self):
        restaurant = get_request_restaurant(self.request)
        self.feature_gate_service_class().ensure_hall_access(restaurant=restaurant)
        return (
            Hall.objects.filter(zone_or_cabin__restaurant=restaurant, is_active=True)
            .select_related('zone_or_cabin')
            .prefetch_related('tables__table_sessions__orders__kitchen_tickets', 'tables__table_sessions__assigned_waiter')
            .order_by('sort_order', 'name')
        )
