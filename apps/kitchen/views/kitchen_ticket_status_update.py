from rest_framework import generics, permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.kitchen.models import KitchenTicket
from apps.kitchen.services.kitchen_status import KitchenStatusService
from common.api.permissions import HasPermissionCode
from common.api.scopes import get_request_branch


class KitchenTicketStatusUpdateView(APIView):
    permission_classes = [permissions.IsAuthenticated, HasPermissionCode]
    permission_code = 'kitchen.manage'
    kitchen_status_service_class = KitchenStatusService

    def post(self, request, pk):
        branch = get_request_branch(request)
        ticket = generics.get_object_or_404(KitchenTicket.objects.select_related('order', 'prep_station'), pk=pk, branch=branch)
        serializer_data = self.kitchen_status_service_class().update_ticket_status(ticket=ticket, status=request.data.get('status'))
        return Response(serializer_data)
