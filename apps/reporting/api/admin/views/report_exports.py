from apps.catalog.models import CatalogCategory
from apps.floor.models import Hall
from apps.reporting.helpers import (
    OpenChecksReportFilters,
    PaymentBreakdownReportFilters,
    ReceiptsReportFilters,
    SalesReportFilters,
    ShiftReportFilters,
    SummaryReportFilters,
    TopItemsReportFilters,
    TopStaffReportFilters,
    build_excel_attachment,
)
from apps.reporting.services import (
    REPORT_TITLE_OPEN_CHECKS,
    REPORT_TITLE_PAYMENT_BREAKDOWN,
    REPORT_TITLE_RECEIPTS,
    REPORT_TITLE_SALES,
    REPORT_TITLE_SHIFTS,
    REPORT_TITLE_SUMMARY,
    REPORT_TITLE_TOP_ITEMS,
    REPORT_TITLE_TOP_STAFF,
    ReportExcelExportService,
    build_summary_payload,
    get_open_checks_columns,
    get_open_checks_report_queryset,
    get_payment_breakdown_report_queryset,
    get_receipts_columns,
    get_receipts_report_queryset,
    get_report_export_filename,
    get_report_title,
    get_sales_columns,
    get_sales_report_queryset,
    get_shift_columns,
    get_shift_report_queryset,
    get_summary_metrics,
    get_top_items_columns,
    get_top_items_report_queryset,
    get_top_staff_columns,
    get_top_staff_report_queryset,
    localize_open_checks_rows,
    localize_payment_breakdown_rows,
    localize_receipt_rows,
    localize_sales_rows,
    localize_shift_rows,
)
from apps.restaurants.models import CashDesk
from apps.users.models import User

from .report_base import AdminBaseReportView


def build_report_attachment(*, payload: bytes, title: str, period):
    return build_excel_attachment(payload, filename=get_report_export_filename(title, period))


class SummaryReportExportView(AdminBaseReportView):
    export_service_class = ReportExcelExportService

    def get(self, request):
        filters = SummaryReportFilters.from_request(request)
        summary = build_summary_payload(self.get_restaurant(), filters.period)
        payload = self.export_service_class().build_summary_file(
            title=get_report_title(REPORT_TITLE_SUMMARY),
            metrics=get_summary_metrics(summary),
            filters=self.get_filter_pairs(filters.period),
        )
        return build_report_attachment(payload=payload, title=REPORT_TITLE_SUMMARY, period=filters.period)


class SalesReportExportView(AdminBaseReportView):
    export_service_class = ReportExcelExportService

    def get(self, request):
        filters = SalesReportFilters.from_request(request)
        rows = localize_sales_rows(list(filters.apply(get_sales_report_queryset(self.get_restaurant(), filters.period))))
        payload = self.export_service_class().build_table_file(
            title=get_report_title(REPORT_TITLE_SALES),
            columns=get_sales_columns(),
            rows=rows,
            filters=self.get_filter_pairs(
                filters.period,
                [('payment_method', filters.payment_method), ('search', filters.search)],
            ),
        )
        return build_report_attachment(payload=payload, title=REPORT_TITLE_SALES, period=filters.period)


class OpenChecksReportExportView(AdminBaseReportView):
    export_service_class = ReportExcelExportService

    def get(self, request):
        filters = OpenChecksReportFilters.from_request(request)
        rows = localize_open_checks_rows(
            list(filters.apply(get_open_checks_report_queryset(self.get_restaurant(), filters.period)))
        )
        payload = self.export_service_class().build_table_file(
            title=get_report_title(REPORT_TITLE_OPEN_CHECKS),
            columns=get_open_checks_columns(),
            rows=rows,
            filters=self.get_filter_pairs(
                filters.period,
                [
                    ('status', filters.status),
                    (
                        'hall',
                        self.resolve_filter_name(
                            Hall,
                            filters.hall_id,
                            restaurant_lookup='zone_or_cabin__restaurant',
                        ),
                    ),
                    ('search', filters.search),
                ],
            ),
        )
        return build_report_attachment(payload=payload, title=REPORT_TITLE_OPEN_CHECKS, period=filters.period)


class ReceiptsReportExportView(AdminBaseReportView):
    export_service_class = ReportExcelExportService

    def get(self, request):
        filters = ReceiptsReportFilters.from_request(request)
        rows = localize_receipt_rows(
            list(filters.apply(get_receipts_report_queryset(self.get_restaurant(), filters.period)))
        )
        payload = self.export_service_class().build_table_file(
            title=get_report_title(REPORT_TITLE_RECEIPTS),
            columns=get_receipts_columns(),
            rows=rows,
            filters=self.get_filter_pairs(
                filters.period,
                [
                    ('receipt_kind', filters.kind),
                    ('receipt_status', filters.status),
                    ('search', filters.search),
                ],
            ),
        )
        return build_report_attachment(payload=payload, title=REPORT_TITLE_RECEIPTS, period=filters.period)


class TopItemsReportExportView(AdminBaseReportView):
    export_service_class = ReportExcelExportService

    def get(self, request):
        filters = TopItemsReportFilters.from_request(request)
        rows = list(filters.apply(get_top_items_report_queryset(self.get_restaurant(), filters.period)))
        payload = self.export_service_class().build_table_file(
            title=get_report_title(REPORT_TITLE_TOP_ITEMS),
            columns=get_top_items_columns(),
            rows=rows,
            filters=self.get_filter_pairs(
                filters.period,
                [
                    ('category', self.resolve_filter_name(CatalogCategory, filters.category_id)),
                    ('search', filters.search),
                ],
            ),
        )
        return build_report_attachment(payload=payload, title=REPORT_TITLE_TOP_ITEMS, period=filters.period)


class TopStaffReportExportView(AdminBaseReportView):
    export_service_class = ReportExcelExportService

    def get(self, request):
        filters = TopStaffReportFilters.from_request(request)
        rows = list(filters.apply(get_top_staff_report_queryset(self.get_restaurant(), filters.period)))
        payload = self.export_service_class().build_table_file(
            title=get_report_title(REPORT_TITLE_TOP_STAFF),
            columns=get_top_staff_columns(),
            rows=rows,
            filters=self.get_filter_pairs(filters.period, [('search', filters.search)]),
        )
        return build_report_attachment(payload=payload, title=REPORT_TITLE_TOP_STAFF, period=filters.period)


class PaymentBreakdownExportView(AdminBaseReportView):
    export_service_class = ReportExcelExportService

    def get(self, request):
        filters = PaymentBreakdownReportFilters.from_request(request)
        rows = localize_payment_breakdown_rows(
            list(filters.apply(get_payment_breakdown_report_queryset(self.get_restaurant(), filters.period)))
        )
        payload = self.export_service_class().build_table_file(
            title=get_report_title(REPORT_TITLE_PAYMENT_BREAKDOWN),
            columns=get_sales_columns(),
            rows=rows,
            filters=self.get_filter_pairs(
                filters.period,
                [('payment_method', filters.payment_method), ('search', filters.search)],
            ),
        )
        return build_report_attachment(payload=payload, title=REPORT_TITLE_PAYMENT_BREAKDOWN, period=filters.period)


class ShiftReportExportView(AdminBaseReportView):
    export_service_class = ReportExcelExportService

    def get(self, request):
        filters = ShiftReportFilters.from_request(request)
        rows = localize_shift_rows(list(filters.apply(get_shift_report_queryset(self.get_restaurant(), filters.period))))
        payload = self.export_service_class().build_table_file(
            title=get_report_title(REPORT_TITLE_SHIFTS),
            columns=get_shift_columns(),
            rows=rows,
            filters=self.get_filter_pairs(
                filters.period,
                [
                    ('status', filters.statuses[0] if filters.statuses else ''),
                    ('cash_desk', self.resolve_filter_name(CashDesk, filters.cash_desk_id)),
                    (
                        'cashier',
                        self.resolve_filter_name(
                            User,
                            filters.cashier_id,
                            name_field='full_name',
                            restaurant_lookup='restaurant_profile__restaurant',
                        ),
                    ),
                    ('difference_only', 'true' if filters.difference_only else ''),
                    ('search', filters.search),
                ],
            ),
        )
        return build_report_attachment(payload=payload, title=REPORT_TITLE_SHIFTS, period=filters.period)
