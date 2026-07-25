from rest_framework import generics, permissions

from apps.floor.models import TableSession
from apps.floor.api.admin.serializers import TableSessionSerializer
from common.api.permissions import EndpointRBACPermission
from common.api.scope_filters import filter_queryset_by_optional_restaurant


class TableSessionDetailView(generics.RetrieveUpdateAPIView):
    serializer_class = TableSessionSerializer
    permission_classes = [permissions.IsAuthenticated, EndpointRBACPermission]

    def get_queryset(self):
        return filter_queryset_by_optional_restaurant(
            TableSession.objects.select_related(
                "restaurant", "table", "hall", "opened_by", "assigned_waiter"
            ),
            self.request,
        )
