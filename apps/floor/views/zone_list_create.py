from rest_framework import generics, permissions

from apps.floor.models import ZoneOrCabin
from apps.floor.serializers import ZoneOrCabinSerializer
from common.api.permissions import HasPermissionCode
from common.api.scopes import get_request_restaurant


class ZoneListCreateView(generics.ListCreateAPIView):
    serializer_class = ZoneOrCabinSerializer
    permission_classes = [permissions.IsAuthenticated, HasPermissionCode]
    permission_code = 'constructor.manage'

    def get_queryset(self):
        restaurant = get_request_restaurant(self.request)
        return ZoneOrCabin.objects.filter(hall__restaurant=restaurant).select_related('hall')
