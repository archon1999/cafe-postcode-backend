from rest_framework import generics, permissions

from apps.floor.api.admin.serializers import HallSerializer
from apps.floor.selectors.pos_halls import pos_hall_queryset
from apps.platform.services import FeatureGateService
from common.api.permissions import EndpointRBACPermission
from common.api.scopes import get_request_restaurant


class PosHallListView(generics.ListAPIView):
    serializer_class = HallSerializer
    permission_classes = [permissions.IsAuthenticated, EndpointRBACPermission]
    feature_gate_service_class = FeatureGateService

    def get_queryset(self):
        restaurant = get_request_restaurant(self.request)
        self.feature_gate_service_class().ensure_hall_access(restaurant=restaurant)

        return pos_hall_queryset(restaurant=restaurant)
