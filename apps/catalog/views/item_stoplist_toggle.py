from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.catalog.models import CatalogItem
from apps.catalog.serializers import CatalogItemSerializer
from common.api.permissions import EndpointRBACPermission
from common.api.scopes import get_request_restaurant


class ItemStoplistToggleView(APIView):
    permission_classes = [permissions.IsAuthenticated, EndpointRBACPermission]

    def post(self, request, pk):
        restaurant = get_request_restaurant(request)
        item = generics.get_object_or_404(CatalogItem, pk=pk, restaurant=restaurant)
        item.is_stoplisted = not item.is_stoplisted
        item.save(update_fields=['is_stoplisted', 'updated_at'])
        return Response(CatalogItemSerializer(item).data, status=status.HTTP_200_OK)
