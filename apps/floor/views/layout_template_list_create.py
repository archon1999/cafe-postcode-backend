from rest_framework import generics, permissions

from apps.floor.models import LayoutTemplate
from apps.floor.serializers import LayoutTemplateSerializer
from common.api.permissions import HasPermissionCode
from common.api.scopes import get_request_restaurant


class LayoutTemplateListCreateView(generics.ListCreateAPIView):
    serializer_class = LayoutTemplateSerializer
    permission_classes = [permissions.IsAuthenticated, HasPermissionCode]
    permission_code = 'constructor.manage'

    def get_queryset(self):
        restaurant = get_request_restaurant(self.request)
        return LayoutTemplate.objects.filter(restaurant=restaurant).order_by('name')

    def perform_create(self, serializer):
        serializer.save(restaurant=get_request_restaurant(self.request))
