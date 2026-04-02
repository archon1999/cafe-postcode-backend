from rest_framework import generics, permissions

from apps.floor.models import DiningTable
from apps.floor.serializers import DiningTableSerializer
from common.api.permissions import EndpointRBACPermission
from common.api.scopes import get_request_restaurant


class DiningTableDetailView(generics.RetrieveUpdateAPIView):
    serializer_class = DiningTableSerializer
    permission_classes = [permissions.IsAuthenticated, EndpointRBACPermission]

    def get_queryset(self):
        restaurant = get_request_restaurant(self.request)
        return (
            DiningTable.objects.filter(hall__zone_or_cabin__restaurant=restaurant)
            .select_related('hall', 'zone')
            .prefetch_related('table_sessions')
        )
