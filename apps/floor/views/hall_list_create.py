from rest_framework import generics, permissions

from apps.floor.models import Hall
from apps.floor.serializers import HallSerializer
from common.api.permissions import HasPermissionCode
from common.api.scopes import get_request_branch, get_request_restaurant


class HallListCreateView(generics.ListCreateAPIView):
    serializer_class = HallSerializer
    permission_classes = [permissions.IsAuthenticated, HasPermissionCode]
    permission_code = 'constructor.manage'

    def get_queryset(self):
        restaurant = get_request_restaurant(self.request)
        return Hall.objects.filter(restaurant=restaurant).prefetch_related('tables__table_sessions')

    def perform_create(self, serializer):
        restaurant = get_request_restaurant(self.request)
        serializer.save(restaurant=restaurant, branch=get_request_branch(self.request, restaurant))
