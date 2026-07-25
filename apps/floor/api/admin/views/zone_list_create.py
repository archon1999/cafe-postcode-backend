from rest_framework import generics, permissions

from apps.floor.models import ZoneOrCabin
from apps.floor.api.admin.serializers import ZoneOrCabinSerializer
from common.api.permissions import EndpointRBACPermission
from common.api.scopes import get_request_restaurant
from common.api.scope_filters import filter_queryset_by_optional_restaurant


class ZoneListCreateView(generics.ListCreateAPIView):
    serializer_class = ZoneOrCabinSerializer
    permission_classes = [permissions.IsAuthenticated, EndpointRBACPermission]

    def get_queryset(self):
        return filter_queryset_by_optional_restaurant(
            ZoneOrCabin.objects.select_related("restaurant"),
            self.request,
        )

    def perform_create(self, serializer):
        serializer.save(restaurant=get_request_restaurant(self.request))
