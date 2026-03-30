from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.dashboard.permissions import IsOwnerDashboardUser
from apps.dashboard.serializers import DashboardOverviewSerializer
from apps.dashboard.services import OwnerDashboardOverviewService
from common.api.scopes import get_request_branch
from apps.organizations.services import FeatureGateService


class DashboardOverviewView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsOwnerDashboardUser]
    overview_service_class = OwnerDashboardOverviewService
    feature_gate_service_class = FeatureGateService

    def get(self, request):
        branch = get_request_branch(request)
        self.feature_gate_service_class().ensure_owner_dashboard_access(restaurant=branch.restaurant)
        payload = self.overview_service_class().build(branch=branch)
        serializer = DashboardOverviewSerializer(payload)
        return Response(serializer.data)
