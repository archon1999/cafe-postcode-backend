from rest_framework import permissions
from rest_framework.views import APIView

from apps.reports.services import build_summary_payload, get_report_period
from common.api.permissions import EndpointRBACPermission
from common.api.scopes import get_request_restaurant


class BaseReportView(APIView):
    permission_classes = [permissions.IsAuthenticated, EndpointRBACPermission]

    def get_restaurant(self):
        return get_request_restaurant(self.request)

    def get_period(self):
        return get_report_period(self.request.query_params)

    def get_summary_payload(self, restaurant, period):
        return build_summary_payload(restaurant, period)
