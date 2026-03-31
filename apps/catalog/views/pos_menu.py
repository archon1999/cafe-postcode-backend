from rest_framework import generics, permissions

from apps.catalog.models import CatalogCategory
from apps.catalog.serializers import CatalogMenuCategorySerializer
from common.api.permissions import HasPermissionCode
from common.api.scopes import get_request_restaurant


class PosMenuView(generics.ListAPIView):
    serializer_class = CatalogMenuCategorySerializer
    permission_classes = [permissions.IsAuthenticated, HasPermissionCode]
    permission_code = 'catalog.view'

    def get_queryset(self):
        restaurant = get_request_restaurant(self.request)
        return CatalogCategory.objects.filter(restaurant=restaurant, is_active=True).prefetch_related('items__prep_station')
