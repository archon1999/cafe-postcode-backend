from django.db.models import Prefetch
from rest_framework import generics, permissions

from apps.catalog.models import CatalogItemGroup, CatalogItemGroupMember
from apps.catalog.serializers import CatalogItemGroupSerializer
from common.api.permissions import EndpointRBACPermission
from common.api.scopes import get_request_restaurant


def item_group_queryset(request):
    queryset = CatalogItemGroup.objects.filter(
        restaurant=get_request_restaurant(request)
    ).select_related('category').prefetch_related(
        Prefetch(
            'members',
            queryset=CatalogItemGroupMember.objects.select_related('catalog_item').order_by(
                'sort_order', 'catalog_item__sort_order', 'catalog_item__name'
            ),
        )
    )
    category_id = request.query_params.get('category') or request.query_params.get('category_id')
    if category_id:
        queryset = queryset.filter(category_id=category_id)
    return queryset.order_by('sort_order', 'name')


class ItemGroupListCreateView(generics.ListCreateAPIView):
    serializer_class = CatalogItemGroupSerializer
    permission_classes = [permissions.IsAuthenticated, EndpointRBACPermission]
    pagination_class = None

    def get_queryset(self):
        return item_group_queryset(self.request)

    def perform_create(self, serializer):
        serializer.save(restaurant=get_request_restaurant(self.request))


class ItemGroupDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = CatalogItemGroupSerializer
    permission_classes = [permissions.IsAuthenticated, EndpointRBACPermission]

    def get_queryset(self):
        return item_group_queryset(self.request)
