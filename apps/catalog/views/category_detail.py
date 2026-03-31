from rest_framework import generics, permissions

from apps.catalog.models import CatalogCategory
from apps.catalog.serializers import CatalogCategorySerializer
from common.api.permissions import EndpointRBACPermission
from common.api.scopes import get_request_restaurant


class CategoryDetailView(generics.RetrieveUpdateAPIView):
    serializer_class = CatalogCategorySerializer
    permission_classes = [permissions.IsAuthenticated, EndpointRBACPermission]

    def get_queryset(self):
        restaurant = get_request_restaurant(self.request)
        return CatalogCategory.objects.filter(restaurant=restaurant)
