from rest_framework import generics, permissions

from apps.floor.api.admin.serializers import TableSessionSerializer
from apps.floor.models import DiningTable, TableSession
from apps.floor.selectors.floor import TableSessionListFilters
from apps.floor.services import sync_table_status
from apps.platform.services import FeatureGateService
from common.api.permissions import (
    EndpointRBACPermission,
    POS_TABLE_RESERVATIONS_MANAGE_PERMISSION,
    POS_TABLES_MANAGE_PERMISSION,
    require_any_permission_code,
)
from common.api.scope_filters import filter_queryset_by_optional_restaurant
from common.api.scopes import get_optional_request_restaurant, get_request_restaurant


class TableSessionListCreateView(generics.ListCreateAPIView):
    serializer_class = TableSessionSerializer
    permission_classes = [permissions.IsAuthenticated, EndpointRBACPermission]
    feature_gate_service_class = FeatureGateService

    def get_queryset(self):
        restaurant = get_optional_request_restaurant(self.request)
        if restaurant is not None:
            self.feature_gate_service_class().ensure_hall_access(restaurant=restaurant)

        queryset = filter_queryset_by_optional_restaurant(
            TableSession.objects.select_related(
                "restaurant", "table", "hall", "opened_by", "assigned_waiter"
            ),
            self.request,
        )
        return TableSessionListFilters.from_request(self.request).apply(queryset)

    def perform_create(self, serializer):
        restaurant = get_request_restaurant(self.request)
        self.feature_gate_service_class().ensure_hall_access(restaurant=restaurant)
        table = serializer.validated_data["table"]
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
        table.save(update_fields=["status", "updated_at"])
        sync_table_status(table)
