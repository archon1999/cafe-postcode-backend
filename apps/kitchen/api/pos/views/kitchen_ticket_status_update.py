from django.db import transaction
from rest_framework import generics, permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.kitchen.models import KitchenTicket
from apps.kitchen.services.kitchen_status import KitchenStatusService
from common.api.permissions import EndpointRBACPermission
from common.api.scopes import get_request_restaurant


class KitchenTicketStatusUpdateView(APIView):
    permission_classes = [permissions.IsAuthenticated, EndpointRBACPermission]
    kitchen_status_service_class = KitchenStatusService

    @transaction.atomic
    def post(self, request, pk):
        restaurant = get_request_restaurant(request)
        ticket = generics.get_object_or_404(
            KitchenTicket.objects.select_for_update(of=('self',)).select_related('order', 'prep_station'),
            pk=pk,
            restaurant=restaurant,
        )
        serializer_data = self.kitchen_status_service_class().update_ticket_status(
            ticket=ticket,
            status=request.data.get('status'),
            user=request.user,
        )
        return Response(serializer_data)
