from rest_framework.response import Response

from apps.reports.services import get_payment_breakdown_report_queryset

from .base_report import BaseReportView


class PaymentBreakdownView(BaseReportView):
    def get(self, request):
        branch = self.get_branch()
        period = self.get_period()
        rows = get_payment_breakdown_report_queryset(branch, period).order_by('-total')
        return Response(list(rows))
