from rest_framework import generics, permissions

from apps.floor.models import Hall
from apps.floor.api.admin.serializers import HallSerializer
from common.api.permissions import EndpointRBACPermission
from common.api.scope_filters import filter_queryset_by_optional_restaurant


class HallDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = HallSerializer
    permission_classes = [permissions.IsAuthenticated, EndpointRBACPermission]

    def get_queryset(self):
        queryset = Hall.objects.select_related(
            "zone_or_cabin", "zone_or_cabin__restaurant"
        ).prefetch_related("tables__table_sessions")
        return filter_queryset_by_optional_restaurant(
            queryset,
            self.request,
            lookup="zone_or_cabin__restaurant",
        )
