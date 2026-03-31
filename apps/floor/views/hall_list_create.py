from rest_framework import generics, permissions

from apps.floor.models import Hall
from apps.floor.serializers import HallSerializer
from common.api.permissions import EndpointRBACPermission
from common.api.scopes import get_request_restaurant


class HallListCreateView(generics.ListCreateAPIView):
    serializer_class = HallSerializer
    permission_classes = [permissions.IsAuthenticated, EndpointRBACPermission]

    def get_queryset(self):
        restaurant = get_request_restaurant(self.request)
        return Hall.objects.filter(restaurant=restaurant).prefetch_related('zones', 'tables__table_sessions')

    def perform_create(self, serializer):
        restaurant = get_request_restaurant(self.request)
        serializer.save(restaurant=restaurant)
