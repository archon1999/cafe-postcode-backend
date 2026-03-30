from rest_framework import generics, permissions

from apps.catalog.models import CatalogItem
from apps.catalog.serializers import CatalogItemSerializer
from common.api.permissions import HasPermissionCode
from common.api.scopes import get_request_restaurant


class ItemDetailView(generics.RetrieveUpdateAPIView):
    serializer_class = CatalogItemSerializer
    permission_classes = [permissions.IsAuthenticated, HasPermissionCode]
    permission_code = 'catalog.manage'

    def get_queryset(self):
        restaurant = get_request_restaurant(self.request)
        return CatalogItem.objects.filter(restaurant=restaurant).select_related('category', 'prep_station')
