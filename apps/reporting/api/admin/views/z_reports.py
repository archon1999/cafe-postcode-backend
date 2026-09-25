from django.utils.translation import gettext as _

from apps.reporting.helpers import build_excel_attachment
from apps.reporting.selectors.z_reports import build_z_report_row, get_z_report_queryset
from apps.reporting.services import ReportExcelExportService

from .report_base import AdminPaginatedReportView


class ZReportView(AdminPaginatedReportView):
    def get(self, request):
        queryset = get_z_report_queryset(self.get_restaurant(), self.get_period(), request.query_params)
        return self.get_paginated_response([build_z_report_row(row) for row in self.paginate_queryset(queryset)])


class ZReportExportView(AdminPaginatedReportView):
    def get(self, request):
        period = self.get_period()
        queryset = get_z_report_queryset(self.get_restaurant(), period, request.query_params)
        columns = [
            ('cash_desk_name', _('Cash desk')), ('cashier_name', _('Cashier')),
            ('terminal_id', _('Terminal ID')), ('opened_at', _('Opened at')),
            ('closed_at', _('Closed at')), ('cash_total', _('Cash (UZS)')),
            ('card_total', _('Card (UZS)')), ('qr_total', _('QR (UZS)')),
            ('sale_total', _('Sales (UZS)')), ('refund_total', _('Refunds (UZS)')),
            ('sale_count', _('Sale count')), ('refund_count', _('Refund count')),
        ]
        payload = ReportExcelExportService().build_table_file(
            title=_('Z reports'), columns=columns,
            rows=[build_z_report_row(row) for row in queryset],
            filters=self.get_filter_pairs(period),
        )
        return build_excel_attachment(payload, filename='z-reports.xlsx')
