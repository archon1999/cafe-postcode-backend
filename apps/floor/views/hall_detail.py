from rest_framework import generics, permissions

from apps.floor.models import Hall
from apps.floor.serializers import HallSerializer
from common.api.permissions import HasPermissionCode
from common.api.scopes import get_request_restaurant


class HallDetailView(generics.RetrieveUpdateAPIView):
    serializer_class = HallSerializer
    permission_classes = [permissions.IsAuthenticated, HasPermissionCode]
    permission_code = 'constructor.manage'

    def get_queryset(self):
        restaurant = get_request_restaurant(self.request)
        return Hall.objects.filter(restaurant=restaurant).prefetch_related('zones', 'tables__table_sessions')
