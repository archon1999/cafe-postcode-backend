from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.dashboard.serializers import DashboardOverviewSerializer
from apps.dashboard.services import OwnerDashboardOverviewService
from apps.platform.services import FeatureGateService
from common.api.permissions import EndpointRBACPermission
from common.api.scopes import get_request_restaurant


class DashboardOverviewView(APIView):
    permission_classes = [permissions.IsAuthenticated, EndpointRBACPermission]
    overview_service_class = OwnerDashboardOverviewService
    feature_gate_service_class = FeatureGateService

    def get(self, request):
        restaurant = get_request_restaurant(request)
        self.feature_gate_service_class().ensure_owner_dashboard_access(restaurant=restaurant)
        payload = self.overview_service_class().build(restaurant=restaurant)
        serializer = DashboardOverviewSerializer(payload)
        return Response(serializer.data)
