from django.db.models import Prefetch
from rest_framework import generics, permissions

from apps.catalog.models import CatalogCategory, CatalogItem, CatalogItemGroup, CatalogItemGroupMember
from apps.catalog.serializers import CatalogMenuCategorySerializer
from apps.catalog.selectors import active_modifier_assignments_prefetch
from common.api.permissions import EndpointRBACPermission
from common.api.scopes import get_request_restaurant


class PosMenuView(generics.ListAPIView):
    serializer_class = CatalogMenuCategorySerializer
    permission_classes = [permissions.IsAuthenticated, EndpointRBACPermission]

    def get_queryset(self):
        restaurant = get_request_restaurant(self.request)
        item_queryset = CatalogItem.objects.filter(is_active=True, is_stoplisted=False).order_by(
            'sort_order', 'name'
        ).select_related(
            'category__prep_station',
            'prep_station',
        ).prefetch_related(active_modifier_assignments_prefetch())
        group_member_queryset = CatalogItemGroupMember.objects.filter(
            catalog_item__is_active=True,
            catalog_item__is_stoplisted=False,
        ).select_related(
            'catalog_item__category__prep_station',
            'catalog_item__prep_station',
        ).prefetch_related(
            Prefetch(
                'catalog_item__modifier_assignments',
                queryset=active_modifier_assignments_prefetch().queryset,
                to_attr='active_modifier_assignments',
            )
        ).order_by('sort_order', 'catalog_item__sort_order', 'catalog_item__name')
        group_queryset = CatalogItemGroup.objects.filter(is_active=True).prefetch_related(
            Prefetch('members', queryset=group_member_queryset)
        ).order_by('sort_order', 'name')
        return CatalogCategory.objects.filter(restaurant=restaurant, is_active=True).select_related('prep_station').prefetch_related(
            Prefetch('items', queryset=item_queryset, to_attr='active_menu_items'),
            Prefetch('item_groups', queryset=group_queryset, to_attr='active_item_groups'),
        )
