from rest_framework import permissions
from rest_framework.views import APIView

from apps.reports.services import build_summary_payload, get_report_period
from common.api.permissions import HasPermissionCode
from common.api.scopes import get_request_branch


class BaseReportView(APIView):
    permission_classes = [permissions.IsAuthenticated, HasPermissionCode]
    permission_code = 'reports.view'

    def get_branch(self):
        return get_request_branch(self.request)

    def get_period(self):
        return get_report_period(self.request.query_params)

    def get_summary_payload(self, branch, period):
        return build_summary_payload(branch, period)
