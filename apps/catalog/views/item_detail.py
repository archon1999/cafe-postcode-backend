from rest_framework import generics, permissions

from apps.catalog.helpers import filter_catalog_queryset_by_scope
from apps.catalog.models import CatalogItem
from apps.catalog.serializers import CatalogItemSerializer
from common.api.permissions import EndpointRBACPermission


class ItemDetailView(generics.RetrieveUpdateAPIView):
    serializer_class = CatalogItemSerializer
    permission_classes = [permissions.IsAuthenticated, EndpointRBACPermission]

    def get_queryset(self):
        return filter_catalog_queryset_by_scope(CatalogItem.objects.all(), self.request).select_related(
            'category__prep_station',
            'prep_station',
        )
