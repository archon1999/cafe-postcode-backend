from rest_framework import generics, permissions

from apps.floor.models import DiningTable
from apps.floor.api.admin.serializers import DiningTableSerializer
from common.api.permissions import EndpointRBACPermission
from common.api.scope_filters import filter_queryset_by_optional_restaurant


class DiningTableDetailView(generics.RetrieveUpdateAPIView):
    serializer_class = DiningTableSerializer
    permission_classes = [permissions.IsAuthenticated, EndpointRBACPermission]

    def get_queryset(self):
        queryset = DiningTable.objects.select_related(
            "hall", "zone", "hall__zone_or_cabin__restaurant"
        ).prefetch_related("table_sessions")
        return filter_queryset_by_optional_restaurant(
            queryset,
            self.request,
            lookup="hall__zone_or_cabin__restaurant",
        )
