from rest_framework import generics, permissions

from apps.floor.models import ZoneOrCabin
from apps.floor.api.admin.serializers import ZoneOrCabinSerializer
from common.api.permissions import EndpointRBACPermission
from common.api.scopes import get_request_restaurant


class ZoneDetailView(generics.RetrieveUpdateAPIView):
    serializer_class = ZoneOrCabinSerializer
    permission_classes = [permissions.IsAuthenticated, EndpointRBACPermission]

    def get_queryset(self):
        restaurant = get_request_restaurant(self.request)
        return ZoneOrCabin.objects.filter(restaurant=restaurant)
