from rest_framework.response import Response

from apps.reports.services import get_sales_report_queryset

from .base_report import BaseReportView


class SalesReportView(BaseReportView):
    def get(self, request):
        branch = self.get_branch()
        period = self.get_period()
        rows = get_sales_report_queryset(branch, period).order_by('method')
        return Response(list(rows))
