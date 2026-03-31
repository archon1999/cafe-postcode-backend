from django.http import HttpResponse

from apps.reports.services import (
    SalesReportExcelExportService,
    get_open_checks_report_queryset,
    get_payment_breakdown_report_queryset,
    get_sales_report_queryset,
)

from .base_report import BaseReportView


class SalesReportExportView(BaseReportView):
    export_service_class = SalesReportExcelExportService

    def get(self, request):
        restaurant = self.get_restaurant()
        period = self.get_period()
        summary = self.get_summary_payload(restaurant, period)
        sales_rows = list(get_sales_report_queryset(restaurant, period).order_by('method'))
        payment_rows = list(get_payment_breakdown_report_queryset(restaurant, period).order_by('-total'))
        open_check_rows = list(get_open_checks_report_queryset(restaurant, period).order_by('-created_at'))
        exporter = self.export_service_class()
        payload = exporter.build_file(summary, sales_rows, payment_rows, open_check_rows)
        response = HttpResponse(
            payload,
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )
        response['Content-Disposition'] = 'attachment; filename="daily-sales-report.xlsx"'
        return response
