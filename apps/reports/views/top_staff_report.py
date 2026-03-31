from rest_framework.response import Response

from apps.reports.services import get_top_staff_report_queryset

from .base_report import BaseReportView


class TopStaffReportView(BaseReportView):
    def get(self, request):
        restaurant = self.get_restaurant()
        period = self.get_period()
        rows = get_top_staff_report_queryset(restaurant, period).order_by('-total_sales', '-order_count')[:10]
        return Response(list(rows))
