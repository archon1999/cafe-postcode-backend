from django.db import transaction
from django.utils.translation import gettext as _
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.orders.models import Order
from apps.orders.serializers import OrderSerializer
from apps.orders.services import OrderSubmissionService
from common.api.permissions import (
    EndpointRBACPermission,
    POS_TABLES_MANAGE_PERMISSION,
    POS_TAKEAWAY_MENU_VIEW_PERMISSION,
    require_any_permission_code,
)
from common.api.scopes import get_request_restaurant


class OrderSubmitView(APIView):
    permission_classes = [permissions.IsAuthenticated, EndpointRBACPermission]
    order_submission_service_class = OrderSubmissionService

    @transaction.atomic
    def post(self, request, pk):
        restaurant = get_request_restaurant(request)
        order = generics.get_object_or_404(Order, pk=pk, restaurant=restaurant)
        required_permission = POS_TABLES_MANAGE_PERMISSION if order.table_session_id else POS_TAKEAWAY_MENU_VIEW_PERMISSION
        require_any_permission_code(request.user, required_permission)
        if not order.items.exists():
            return Response({'detail': _('Order has no items.')}, status=status.HTTP_400_BAD_REQUEST)
        self.order_submission_service_class().submit(order)
        return Response(OrderSerializer(order).data)
