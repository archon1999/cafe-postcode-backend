from rest_framework import generics, permissions

from apps.floor.models import TableSession
from apps.floor.serializers import TableSessionSerializer
from common.api.permissions import EndpointRBACPermission
from common.api.scopes import get_request_restaurant


class TableSessionDetailView(generics.RetrieveUpdateAPIView):
    serializer_class = TableSessionSerializer
    permission_classes = [permissions.IsAuthenticated, EndpointRBACPermission]

    def get_queryset(self):
        restaurant = get_request_restaurant(self.request)
        return TableSession.objects.filter(restaurant=restaurant).select_related(
            'table',
            'hall',
            'opened_by',
            'assigned_waiter',
        )
