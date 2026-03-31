from rest_framework import generics, permissions

from apps.catalog.models import CatalogCategory
from apps.catalog.serializers import CatalogCategorySerializer
from common.api.permissions import HasPermissionCode
from common.api.scopes import get_request_restaurant


class CategoryListCreateView(generics.ListCreateAPIView):
    serializer_class = CatalogCategorySerializer
    permission_classes = [permissions.IsAuthenticated, HasPermissionCode]
    permission_code = 'catalog.manage'

    def get_queryset(self):
        restaurant = get_request_restaurant(self.request)
        return CatalogCategory.objects.filter(restaurant=restaurant).order_by('sort_order', 'name')

    def perform_create(self, serializer):
        restaurant = get_request_restaurant(self.request)
        serializer.save(restaurant=restaurant)
