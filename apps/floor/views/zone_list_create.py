from rest_framework import generics, permissions

from apps.floor.models import ZoneOrCabin
from apps.floor.serializers import ZoneOrCabinSerializer
from common.api.permissions import EndpointRBACPermission
from common.api.scopes import get_request_restaurant


class ZoneListCreateView(generics.ListCreateAPIView):
    serializer_class = ZoneOrCabinSerializer
    permission_classes = [permissions.IsAuthenticated, EndpointRBACPermission]

    def get_queryset(self):
        restaurant = get_request_restaurant(self.request)
        return ZoneOrCabin.objects.filter(restaurant=restaurant)

    def perform_create(self, serializer):
        serializer.save(restaurant=get_request_restaurant(self.request))
