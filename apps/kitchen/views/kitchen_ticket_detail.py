from rest_framework import generics, permissions

from apps.kitchen.models import KitchenTicket
from apps.kitchen.serializers import KitchenTicketSerializer
from common.api.permissions import HasPermissionCode
from common.api.scopes import get_request_restaurant


class KitchenTicketDetailView(generics.RetrieveAPIView):
    serializer_class = KitchenTicketSerializer
    permission_classes = [permissions.IsAuthenticated, HasPermissionCode]
    permission_code = 'kitchen.view'

    def get_queryset(self):
        restaurant = get_request_restaurant(self.request)
        return KitchenTicket.objects.filter(restaurant=restaurant).select_related(
            'prep_station',
            'order__table_session__hall',
            'order__table_session__table',
        )
