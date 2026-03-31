from rest_framework import generics, permissions

from apps.organizations.serializers import RestaurantSerializer
from common.api.permissions import EndpointRBACPermission
from common.api.scopes import get_request_restaurant


class RestaurantConfigView(generics.RetrieveUpdateAPIView):
    serializer_class = RestaurantSerializer
    permission_classes = [permissions.IsAuthenticated, EndpointRBACPermission]

    def get_object(self):
        return get_request_restaurant(self.request)
