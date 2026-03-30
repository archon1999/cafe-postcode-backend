from rest_framework import generics, permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.kitchen.services.kitchen_status import KitchenStatusService
from apps.orders.models import OrderItem
from common.api.permissions import HasPermissionCode
from common.api.scopes import get_request_branch


class KitchenItemStatusUpdateView(APIView):
    permission_classes = [permissions.IsAuthenticated, HasPermissionCode]
    permission_code = 'kitchen.manage'
    kitchen_status_service_class = KitchenStatusService

    def post(self, request, pk):
        branch = get_request_branch(request)
        item = generics.get_object_or_404(
            OrderItem.objects.select_related('order__restaurant', 'prep_station'),
            pk=pk,
            order__branch=branch,
        )
        serializer_data = self.kitchen_status_service_class().update_item_status(item=item, status=request.data.get('status'))
        return Response(serializer_data)
