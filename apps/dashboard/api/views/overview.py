from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.dashboard.api.serializers import DashboardOverviewSerializer
from apps.dashboard.services import OwnerDashboardOverviewService, get_dashboard_restaurant_scope
from apps.platform.services import FeatureGateService
from apps.reporting.services import get_report_period
from common.api.permissions import require_any_permission_code


class DashboardOverviewView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    overview_service_class = OwnerDashboardOverviewService
    feature_gate_service_class = FeatureGateService

    def get(self, request):
        require_any_permission_code(request.user, 'dashboard.view')
        scope = get_dashboard_restaurant_scope(request)
        period = get_report_period(request.query_params)
        for restaurant in scope.restaurants:
            self.feature_gate_service_class().ensure_owner_dashboard_access(restaurant=restaurant)
        payload = self.overview_service_class().build(
            restaurant=scope.selected_restaurant,
            restaurant_scope=scope.query_scope,
            is_all=scope.is_all,
            period=period,
        )
        serializer = DashboardOverviewSerializer(payload)
        return Response(serializer.data)
