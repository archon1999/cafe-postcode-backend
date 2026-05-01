from rest_framework import generics, permissions

from apps.kitchen.models import KitchenTicket
from apps.kitchen.api.pos.serializers import KitchenTicketSerializer
from common.api.permissions import EndpointRBACPermission
from common.api.scopes import get_request_restaurant


class KitchenTicketDetailView(generics.RetrieveAPIView):
    serializer_class = KitchenTicketSerializer
    permission_classes = [permissions.IsAuthenticated, EndpointRBACPermission]

    def get_queryset(self):
        restaurant = get_request_restaurant(self.request)
        return KitchenTicket.objects.filter(restaurant=restaurant).select_related(
            'prep_station',
            'order__opened_by',
            'order__table_session__hall',
            'order__table_session__table',
        ).prefetch_related('order__items__catalog_item', 'order__items__prep_station')
