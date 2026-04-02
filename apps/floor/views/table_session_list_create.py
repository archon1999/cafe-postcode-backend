from rest_framework import generics, permissions

from apps.floor.models import DiningTable, TableSession
from apps.floor.serializers import TableSessionSerializer
from apps.organizations.services import FeatureGateService
from common.api.permissions import (
    EndpointRBACPermission,
    POS_TABLE_RESERVATIONS_MANAGE_PERMISSION,
    POS_TABLES_MANAGE_PERMISSION,
    require_any_permission_code,
)
from common.api.scopes import get_request_restaurant


class TableSessionListCreateView(generics.ListCreateAPIView):
    serializer_class = TableSessionSerializer
    permission_classes = [permissions.IsAuthenticated, EndpointRBACPermission]
    feature_gate_service_class = FeatureGateService

    def get_queryset(self):
        restaurant = get_request_restaurant(self.request)
        self.feature_gate_service_class().ensure_hall_access(restaurant=restaurant)
        queryset = TableSession.objects.filter(restaurant=restaurant).select_related(
            'table',
            'hall',
            'opened_by',
            'assigned_waiter',
        )
        status_value = self.request.query_params.get('status')
        if status_value:
            queryset = queryset.filter(status=status_value)
        return queryset

    def perform_create(self, serializer):
        restaurant = get_request_restaurant(self.request)
        self.feature_gate_service_class().ensure_hall_access(restaurant=restaurant)
        table = serializer.validated_data['table']
        required_permission = (
            POS_TABLE_RESERVATIONS_MANAGE_PERMISSION
            if table.status == DiningTable.Status.RESERVED
            else POS_TABLES_MANAGE_PERMISSION
        )
        require_any_permission_code(self.request.user, required_permission)
        serializer.save(
            restaurant=restaurant,
            hall=table.hall,
            opened_by=self.request.user,
            assigned_waiter=self.request.user,
        )
        table.status = DiningTable.Status.OCCUPIED
        table.save(update_fields=['status', 'updated_at'])
