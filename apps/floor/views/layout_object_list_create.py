from rest_framework import generics, permissions

from apps.floor.models import LayoutObject
from apps.floor.serializers import LayoutObjectSerializer
from common.api.permissions import EndpointRBACPermission
from common.api.scopes import get_request_restaurant


class LayoutObjectListCreateView(generics.ListCreateAPIView):
    serializer_class = LayoutObjectSerializer
    permission_classes = [permissions.IsAuthenticated, EndpointRBACPermission]

    def get_queryset(self):
        restaurant = get_request_restaurant(self.request)
        return LayoutObject.objects.filter(hall__restaurant=restaurant).select_related('hall', 'zone', 'table')
