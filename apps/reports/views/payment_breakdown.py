from rest_framework.response import Response

from apps.reports.services import get_payment_breakdown_report_queryset

from .base_report import BaseReportView


class PaymentBreakdownView(BaseReportView):
    def get(self, request):
        restaurant = self.get_restaurant()
        period = self.get_period()
        rows = get_payment_breakdown_report_queryset(restaurant, period).order_by('-total')
        return Response(list(rows))
