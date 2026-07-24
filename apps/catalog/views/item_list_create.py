from rest_framework import generics, permissions

from apps.catalog.helpers import ItemListFilters, filter_catalog_queryset_by_scope
from apps.catalog.models import CatalogItem
from apps.catalog.serializers import CatalogItemSerializer
from common.api.permissions import EndpointRBACPermission
from common.api.scopes import get_request_restaurant


class ItemListCreateView(generics.ListCreateAPIView):
    serializer_class = CatalogItemSerializer
    permission_classes = [permissions.IsAuthenticated, EndpointRBACPermission]

    def get_queryset(self):
        queryset = CatalogItem.objects.all().select_related('category__prep_station', 'prep_station').prefetch_related(
            'modifier_groups'
        )
        queryset = filter_catalog_queryset_by_scope(queryset, self.request)
        return ItemListFilters.from_request(self.request).apply(queryset)

    def perform_create(self, serializer):
        restaurant = get_request_restaurant(self.request)
        serializer.save(restaurant=restaurant)
