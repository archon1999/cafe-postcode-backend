from rest_framework.response import Response

from apps.reports.services import get_top_items_report_queryset

from .base_report import BaseReportView


class TopItemsReportView(BaseReportView):
    def get(self, request):
        branch = self.get_branch()
        period = self.get_period()
        rows = get_top_items_report_queryset(branch, period).order_by('-quantity', '-revenue')[:10]
        return Response(list(rows))
