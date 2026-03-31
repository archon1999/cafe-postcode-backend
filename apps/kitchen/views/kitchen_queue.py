from rest_framework import generics, permissions

from apps.kitchen.models import KitchenTicket
from apps.kitchen.serializers import KitchenTicketSerializer
from apps.organizations.services import FeatureGateService
from common.api.permissions import EndpointRBACPermission
from common.api.scopes import get_request_restaurant


class KitchenQueueView(generics.ListAPIView):
    serializer_class = KitchenTicketSerializer
    permission_classes = [permissions.IsAuthenticated, EndpointRBACPermission]
    feature_gate_service_class = FeatureGateService

    def get_queryset(self):
        restaurant = get_request_restaurant(self.request)
        feature_config = self.feature_gate_service_class().ensure_kitchen_access(restaurant=restaurant)
        if feature_config.kitchen_mode == feature_config.KitchenMode.PRINTER:
            return KitchenTicket.objects.none()

        queryset = KitchenTicket.objects.filter(restaurant=restaurant).select_related(
            'prep_station',
            'order__opened_by',
            'order__table_session__hall',
            'order__table_session__table',
        ).prefetch_related('order__items__catalog_item', 'order__items__prep_station')
        prep_station_id = self.request.query_params.get('prep_station_id')
        if prep_station_id:
            queryset = queryset.filter(prep_station_id=prep_station_id)
        status_value = self.request.query_params.get('status')
        if status_value:
            queryset = queryset.filter(status=status_value)
        return queryset
