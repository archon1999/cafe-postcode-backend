from rest_framework import generics, permissions

from apps.floor.models import TableSession
from apps.floor.api.admin.serializers import TableSessionSerializer
from apps.floor.services import annotate_zone_name_visibility
from common.api.permissions import EndpointRBACPermission
from common.api.scope_filters import filter_queryset_by_optional_restaurant


class TableSessionDetailView(generics.RetrieveUpdateAPIView):
    serializer_class = TableSessionSerializer
    permission_classes = [permissions.IsAuthenticated, EndpointRBACPermission]

    def get_queryset(self):
        return filter_queryset_by_optional_restaurant(
            annotate_zone_name_visibility(TableSession.objects.all()).select_related(
                "restaurant", "table", "hall", "hall__zone_or_cabin", "opened_by", "assigned_waiter"
            ),
            self.request,
        )
