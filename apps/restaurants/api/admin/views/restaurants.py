from rest_framework import generics

from apps.restaurants.api.admin.serializers import RestaurantSerializer
from apps.restaurants.selectors.restaurants import RestaurantListFilters, get_restaurants_queryset_for_request
from common.api.admin_permissions import AdminPermissionRequiredMixin


class RestaurantListCreateView(AdminPermissionRequiredMixin, generics.ListCreateAPIView):
    serializer_class = RestaurantSerializer

    def get_queryset(self):
        queryset = get_restaurants_queryset_for_request(self.request)
        return RestaurantListFilters.from_request(self.request).apply(queryset)

    def perform_create(self, serializer):
        business_partner = self.request.user.get_business_partner_scope()
        serializer.save(business_partner=business_partner)


class RestaurantDetailView(AdminPermissionRequiredMixin, generics.RetrieveUpdateDestroyAPIView):
    serializer_class = RestaurantSerializer

    def get_queryset(self):
        return get_restaurants_queryset_for_request(self.request)

__all__ = ['RestaurantDetailView', 'RestaurantListCreateView']
