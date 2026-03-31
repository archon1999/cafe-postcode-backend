from rest_framework import generics, permissions

from apps.organizations.models import DistributionPoint
from apps.organizations.serializers import DistributionPointSerializer
from common.api.permissions import EndpointRBACPermission
from common.api.scopes import get_request_restaurant


class DistributionPointListCreateView(generics.ListCreateAPIView):
    serializer_class = DistributionPointSerializer
    permission_classes = [permissions.IsAuthenticated, EndpointRBACPermission]

    def get_queryset(self):
        restaurant = get_request_restaurant(self.request)
        return DistributionPoint.objects.filter(restaurant=restaurant).order_by('name')

    def perform_create(self, serializer):
        serializer.save(restaurant=get_request_restaurant(self.request))
