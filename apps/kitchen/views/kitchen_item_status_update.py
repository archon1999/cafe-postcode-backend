from rest_framework import generics, permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.kitchen.services.kitchen_status import KitchenStatusService
from apps.orders.models import OrderItem
from common.api.permissions import EndpointRBACPermission
from common.api.scopes import get_request_restaurant


class KitchenItemStatusUpdateView(APIView):
    permission_classes = [permissions.IsAuthenticated, EndpointRBACPermission]
    kitchen_status_service_class = KitchenStatusService

    def post(self, request, pk):
        restaurant = get_request_restaurant(request)
        item = generics.get_object_or_404(
            OrderItem.objects.select_related('order__restaurant', 'prep_station'),
            pk=pk,
            order__restaurant=restaurant,
        )
        serializer_data = self.kitchen_status_service_class().update_item_status(item=item, status=request.data.get('status'))
        return Response(serializer_data)
