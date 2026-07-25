from rest_framework import generics, permissions

from apps.catalog.helpers import CategoryListFilters, filter_catalog_queryset_by_scope
from apps.catalog.models import CatalogCategory
from apps.catalog.serializers import CatalogCategorySerializer
from common.api.permissions import EndpointRBACPermission
from common.api.scopes import get_request_restaurant


class CategoryListCreateView(generics.ListCreateAPIView):
    serializer_class = CatalogCategorySerializer
    permission_classes = [permissions.IsAuthenticated, EndpointRBACPermission]

    def get_queryset(self):
        queryset = filter_catalog_queryset_by_scope(
            CatalogCategory.objects.select_related("restaurant", "prep_station"),
            self.request,
        )
        return CategoryListFilters.from_request(self.request).apply(queryset)

    def perform_create(self, serializer):
        restaurant = get_request_restaurant(self.request)
        serializer.save(restaurant=restaurant)
