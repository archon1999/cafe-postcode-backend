from rest_framework import generics, permissions

from apps.organizations.serializers import RestaurantSerializer
from common.api.permissions import HasPermissionCode
from common.api.scopes import get_request_restaurant


class RestaurantConfigView(generics.RetrieveUpdateAPIView):
    serializer_class = RestaurantSerializer
    permission_classes = [permissions.IsAuthenticated, HasPermissionCode]
    permission_code = 'constructor.manage'

    def get_object(self):
        return get_request_restaurant(self.request)
