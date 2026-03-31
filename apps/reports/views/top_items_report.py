from rest_framework.response import Response

from apps.reports.services import get_top_items_report_queryset

from .base_report import BaseReportView


class TopItemsReportView(BaseReportView):
    def get(self, request):
        restaurant = self.get_restaurant()
        period = self.get_period()
        rows = get_top_items_report_queryset(restaurant, period).order_by('-quantity', '-revenue')[:10]
        return Response(list(rows))
