from rest_framework.response import Response

from apps.reports.services import get_open_checks_report_queryset

from .base_report import BaseReportView


class OpenChecksReportView(BaseReportView):
    def get(self, request):
        branch = self.get_branch()
        period = self.get_period()
        rows = get_open_checks_report_queryset(branch, period).order_by('-created_at')
        return Response(list(rows))
