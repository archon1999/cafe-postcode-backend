from django.db.models import QuerySet
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.admin.permissions import AdminPermissionRequiredMixin
from apps.admin.support import (
    OpenChecksReportFilters,
    PaymentBreakdownReportFilters,
    SalesReportFilters,
    ShiftReportFilters,
    SummaryReportFilters,
    TopItemsReportFilters,
    TopStaffReportFilters,
    build_excel_attachment,
)
from apps.reports.services import (
    ReportExcelExportService,
    ReportPeriod,
    REPORT_TITLE_OPEN_CHECKS,
    REPORT_TITLE_PAYMENT_BREAKDOWN,
    REPORT_TITLE_SALES,
    REPORT_TITLE_SHIFTS,
    REPORT_TITLE_SUMMARY,
    REPORT_TITLE_TOP_ITEMS,
    REPORT_TITLE_TOP_STAFF,
    build_report_filter_pairs,
    build_summary_payload,
    get_open_checks_columns,
    get_open_checks_report_queryset,
    get_payment_breakdown_report_queryset,
    get_report_period,
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
    localize_sales_rows,
    localize_shift_rows,
)
from common.api.paginations import StandardResultsSetPagination
from common.api.scopes import get_optional_request_restaurant


class AdminBaseReportView(AdminPermissionRequiredMixin, APIView):
    permission_code = 'reports.view'

    def get_restaurant(self):
        return get_optional_request_restaurant(self.request)

    def get_period(self) -> ReportPeriod:
        return get_report_period(self.request.query_params)

    @staticmethod
    def get_filter_pairs(period: ReportPeriod, extra_filters: list[tuple[str, str]] | None = None) -> list[tuple[str, str]]:
        return build_report_filter_pairs(period, extra_filters)


class AdminPaginatedReportView(AdminBaseReportView):
    pagination_class = StandardResultsSetPagination

    def paginate_queryset(self, queryset: QuerySet):
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(queryset, self.request, view=self)
        self.paginator = paginator
        return page

    def get_paginated_response(self, data):
        return self.paginator.get_paginated_response(data)


class DashboardSummaryView(AdminBaseReportView):
    def get(self, request):
        filters = SummaryReportFilters.from_request(request)
        return Response(build_summary_payload(self.get_restaurant(), filters.period))


class SalesReportView(AdminPaginatedReportView):
    def get(self, request):
        filters = SalesReportFilters.from_request(request)
        queryset = filters.apply(get_sales_report_queryset(self.get_restaurant(), filters.period))
        page = self.paginate_queryset(queryset)
        return self.get_paginated_response(list(page))


class OpenChecksReportView(AdminPaginatedReportView):
    def get(self, request):
        filters = OpenChecksReportFilters.from_request(request)
        queryset = filters.apply(get_open_checks_report_queryset(self.get_restaurant(), filters.period))
        page = self.paginate_queryset(queryset)
        return self.get_paginated_response(list(page))


class TopItemsReportView(AdminPaginatedReportView):
    def get(self, request):
        filters = TopItemsReportFilters.from_request(request)
        queryset = filters.apply(get_top_items_report_queryset(self.get_restaurant(), filters.period))
        page = self.paginate_queryset(queryset)
        return self.get_paginated_response(list(page))


class TopStaffReportView(AdminPaginatedReportView):
    def get(self, request):
        filters = TopStaffReportFilters.from_request(request)
        queryset = filters.apply(get_top_staff_report_queryset(self.get_restaurant(), filters.period))
        page = self.paginate_queryset(queryset)
        return self.get_paginated_response(list(page))


class PaymentBreakdownView(AdminPaginatedReportView):
    def get(self, request):
        filters = PaymentBreakdownReportFilters.from_request(request)
        queryset = filters.apply(get_payment_breakdown_report_queryset(self.get_restaurant(), filters.period))
        page = self.paginate_queryset(queryset)
        return self.get_paginated_response(list(page))


class ShiftReportView(AdminPaginatedReportView):
    permission_code = 'reports.shift.view'

    def get(self, request):
        filters = ShiftReportFilters.from_request(request)
        queryset = filters.apply(get_shift_report_queryset(self.get_restaurant(), filters.period))
        page = self.paginate_queryset(queryset)
        return self.get_paginated_response(list(page))


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
        return build_excel_attachment(payload, filename=f'summary-report-{filters.period.file_label}.xlsx')


class SalesReportExportView(AdminBaseReportView):
    export_service_class = ReportExcelExportService

    def get(self, request):
        filters = SalesReportFilters.from_request(request)
        rows = localize_sales_rows(list(filters.apply(get_sales_report_queryset(self.get_restaurant(), filters.period))))
        payload = self.export_service_class().build_table_file(
            title=get_report_title(REPORT_TITLE_SALES),
            columns=get_sales_columns(),
            rows=rows,
            filters=self.get_filter_pairs(filters.period, [('payment_method', filters.payment_method)]),
        )
        return build_excel_attachment(payload, filename=f'sales-report-{filters.period.file_label}.xlsx')


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
            filters=self.get_filter_pairs(filters.period, [('status', filters.status), ('hall', filters.hall_id)]),
        )
        return build_excel_attachment(payload, filename=f'open-checks-report-{filters.period.file_label}.xlsx')


class TopItemsReportExportView(AdminBaseReportView):
    export_service_class = ReportExcelExportService

    def get(self, request):
        filters = TopItemsReportFilters.from_request(request)
        rows = list(filters.apply(get_top_items_report_queryset(self.get_restaurant(), filters.period)))
        payload = self.export_service_class().build_table_file(
            title=get_report_title(REPORT_TITLE_TOP_ITEMS),
            columns=get_top_items_columns(),
            rows=rows,
            filters=self.get_filter_pairs(filters.period, [('category', filters.category_id)]),
        )
        return build_excel_attachment(payload, filename=f'top-items-report-{filters.period.file_label}.xlsx')


class TopStaffReportExportView(AdminBaseReportView):
    export_service_class = ReportExcelExportService

    def get(self, request):
        filters = TopStaffReportFilters.from_request(request)
        rows = list(filters.apply(get_top_staff_report_queryset(self.get_restaurant(), filters.period)))
        payload = self.export_service_class().build_table_file(
            title=get_report_title(REPORT_TITLE_TOP_STAFF),
            columns=get_top_staff_columns(),
            rows=rows,
            filters=self.get_filter_pairs(filters.period),
        )
        return build_excel_attachment(payload, filename=f'top-staff-report-{filters.period.file_label}.xlsx')


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
            filters=self.get_filter_pairs(filters.period, [('payment_method', filters.payment_method)]),
        )
        return build_excel_attachment(payload, filename=f'payment-breakdown-report-{filters.period.file_label}.xlsx')


class ShiftReportExportView(AdminBaseReportView):
    export_service_class = ReportExcelExportService
    permission_code = 'reports.shift.export'

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
                    ('cash_desk', filters.cash_desk_id),
                    ('cashier', filters.cashier_id),
                    ('difference_only', 'true' if filters.difference_only else ''),
                ],
            ),
        )
        return build_excel_attachment(payload, filename=f'shift-report-{filters.period.file_label}.xlsx')
