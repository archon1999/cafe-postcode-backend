from rest_framework import generics, permissions

from apps.restaurants.api.admin.serializers import RestaurantSerializer
from common.api.admin_permissions import AdminPermissionRequiredMixin
from common.api.scopes import get_optional_request_restaurant, get_request_restaurant
from common.exceptions import NotFoundError


class RestaurantConfigView(AdminPermissionRequiredMixin, generics.RetrieveUpdateAPIView):
    serializer_class = RestaurantSerializer

    def get_object(self):
        return get_request_restaurant(self.request)


class MyRestaurantDetailView(generics.RetrieveAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = RestaurantSerializer

    def get_object(self):
        restaurant = get_optional_request_restaurant(self.request)
        if restaurant is None:
            raise NotFoundError('Restaurant is not available for the current user.')
        return restaurant

__all__ = ['MyRestaurantDetailView', 'RestaurantConfigView']
