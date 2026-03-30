from rest_framework import generics, permissions

from apps.catalog.models import CatalogItem
from apps.catalog.serializers import CatalogItemSerializer
from common.api.permissions import HasPermissionCode
from common.api.scopes import get_request_branch


class ItemDetailView(generics.RetrieveUpdateAPIView):
    serializer_class = CatalogItemSerializer
    permission_classes = [permissions.IsAuthenticated, HasPermissionCode]
    permission_code = 'catalog.manage'

    def get_queryset(self):
        branch = get_request_branch(self.request)
        return CatalogItem.objects.filter(branch=branch).select_related('category', 'prep_station')
