from rest_framework import generics, permissions

from apps.catalog.models import CatalogCategory
from apps.catalog.serializers import CatalogMenuCategorySerializer
from common.api.permissions import HasPermissionCode
from common.api.scopes import get_request_branch


class PosMenuView(generics.ListAPIView):
    serializer_class = CatalogMenuCategorySerializer
    permission_classes = [permissions.IsAuthenticated, HasPermissionCode]
    permission_code = 'catalog.view'

    def get_queryset(self):
        branch = get_request_branch(self.request)
        return CatalogCategory.objects.filter(branch=branch, is_active=True).prefetch_related('items__prep_station')
