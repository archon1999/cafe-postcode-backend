from rest_framework import generics, permissions

from apps.catalog.helpers import filter_catalog_queryset_by_scope
from apps.catalog.models import CatalogCategory
from apps.catalog.serializers import CatalogCategorySerializer
from common.api.permissions import EndpointRBACPermission


class CategoryDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = CatalogCategorySerializer
    permission_classes = [permissions.IsAuthenticated, EndpointRBACPermission]

    def get_queryset(self):
        return filter_catalog_queryset_by_scope(CatalogCategory.objects.select_related('prep_station'), self.request)
