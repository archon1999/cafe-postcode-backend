from rest_framework import generics, permissions

from apps.floor.models import LayoutObject
from apps.floor.serializers import LayoutObjectSerializer
from common.api.permissions import HasPermissionCode
from common.api.scopes import get_request_restaurant


class LayoutObjectDetailView(generics.RetrieveUpdateAPIView):
    serializer_class = LayoutObjectSerializer
    permission_classes = [permissions.IsAuthenticated, HasPermissionCode]
    permission_code = 'constructor.manage'

    def get_queryset(self):
        restaurant = get_request_restaurant(self.request)
        return LayoutObject.objects.filter(hall__restaurant=restaurant).select_related('hall', 'zone', 'table')
