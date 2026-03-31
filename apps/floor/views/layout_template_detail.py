from rest_framework import generics, permissions

from apps.floor.models import LayoutTemplate
from apps.floor.serializers import LayoutTemplateSerializer
from common.api.permissions import EndpointRBACPermission
from common.api.scopes import get_request_restaurant


class LayoutTemplateDetailView(generics.RetrieveUpdateAPIView):
    serializer_class = LayoutTemplateSerializer
    permission_classes = [permissions.IsAuthenticated, EndpointRBACPermission]

    def get_queryset(self):
        restaurant = get_request_restaurant(self.request)
        return LayoutTemplate.objects.filter(restaurant=restaurant)
