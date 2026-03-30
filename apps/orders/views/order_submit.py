from django.db import transaction
from django.utils.translation import gettext as _
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.orders.models import Order
from apps.orders.serializers import OrderSerializer
from apps.orders.services import OrderSubmissionService
from common.api.permissions import HasPermissionCode
from common.api.scopes import get_request_branch


class OrderSubmitView(APIView):
    permission_classes = [permissions.IsAuthenticated, HasPermissionCode]
    permission_code = 'orders.manage'
    order_submission_service_class = OrderSubmissionService

    @transaction.atomic
    def post(self, request, pk):
        branch = get_request_branch(request)
        order = generics.get_object_or_404(Order, pk=pk, branch=branch)
        if not order.items.exists():
            return Response({'detail': _('Order has no items.')}, status=status.HTTP_400_BAD_REQUEST)
        self.order_submission_service_class().submit(order)
        return Response(OrderSerializer(order).data)
