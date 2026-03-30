from rest_framework.response import Response

from .base_report import BaseReportView


class DashboardSummaryView(BaseReportView):
    def get(self, request):
        branch = self.get_branch()
        period = self.get_period()
        return Response(self.get_summary_payload(branch, period))
