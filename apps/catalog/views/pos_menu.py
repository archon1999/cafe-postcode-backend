from django.db.models import Prefetch
from rest_framework import generics, permissions

from apps.catalog.models import CatalogCategory, CatalogItem
from apps.catalog.serializers import CatalogMenuCategorySerializer
from apps.catalog.selectors import active_modifier_assignments_prefetch
from common.api.permissions import EndpointRBACPermission
from common.api.scopes import get_request_restaurant


class PosMenuView(generics.ListAPIView):
    serializer_class = CatalogMenuCategorySerializer
    permission_classes = [permissions.IsAuthenticated, EndpointRBACPermission]

    def get_queryset(self):
        restaurant = get_request_restaurant(self.request)
        item_queryset = CatalogItem.objects.filter(is_active=True, is_stoplisted=False).select_related(
            'category__prep_station',
            'prep_station',
        ).prefetch_related(active_modifier_assignments_prefetch())
        return CatalogCategory.objects.filter(restaurant=restaurant, is_active=True).select_related('prep_station').prefetch_related(
            Prefetch('items', queryset=item_queryset, to_attr='active_menu_items')
        )
