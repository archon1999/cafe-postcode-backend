from rest_framework import generics, permissions

from apps.kitchen.models import KitchenTicket
from apps.kitchen.serializers import KitchenTicketSerializer
from common.api.permissions import HasPermissionCode
from common.api.scopes import get_request_branch


class KitchenTicketDetailView(generics.RetrieveAPIView):
    serializer_class = KitchenTicketSerializer
    permission_classes = [permissions.IsAuthenticated, HasPermissionCode]
    permission_code = 'kitchen.view'

    def get_queryset(self):
        branch = get_request_branch(self.request)
        return KitchenTicket.objects.filter(branch=branch).select_related(
            'prep_station',
            'order__table_session__hall',
            'order__table_session__table',
        )
