from rest_framework import generics, permissions

from apps.organizations.models import PrepStation
from apps.organizations.serializers import PrepStationSerializer
from common.api.permissions import EndpointRBACPermission
from common.api.scopes import get_request_restaurant


class PrepStationListCreateView(generics.ListCreateAPIView):
    serializer_class = PrepStationSerializer
    permission_classes = [permissions.IsAuthenticated, EndpointRBACPermission]

    def get_queryset(self):
        restaurant = get_request_restaurant(self.request)
        return PrepStation.objects.filter(restaurant=restaurant).order_by('name')

    def perform_create(self, serializer):
        serializer.save(restaurant=get_request_restaurant(self.request))
