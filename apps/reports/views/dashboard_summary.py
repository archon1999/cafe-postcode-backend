from rest_framework.response import Response

from .base_report import BaseReportView


class DashboardSummaryView(BaseReportView):
    def get(self, request):
        restaurant = self.get_restaurant()
        period = self.get_period()
        return Response(self.get_summary_payload(restaurant, period))
