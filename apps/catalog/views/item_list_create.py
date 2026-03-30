from rest_framework import generics, permissions

from apps.catalog.models import CatalogItem
from apps.catalog.serializers import CatalogItemSerializer
from common.api.permissions import HasPermissionCode
from common.api.scopes import get_request_branch, get_request_restaurant


class ItemListCreateView(generics.ListCreateAPIView):
    serializer_class = CatalogItemSerializer
    permission_classes = [permissions.IsAuthenticated, HasPermissionCode]
    permission_code = 'catalog.manage'

    def get_queryset(self):
        branch = get_request_branch(self.request)
        return CatalogItem.objects.filter(branch=branch).select_related('category', 'prep_station')

    def perform_create(self, serializer):
        restaurant = get_request_restaurant(self.request)
        serializer.save(restaurant=restaurant, branch=get_request_branch(self.request, restaurant))
