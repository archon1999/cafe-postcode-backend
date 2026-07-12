from django.db.models import QuerySet
from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView

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
    ReportPeriod,
    build_report_filter_pairs,
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
from common.api.paginations import StandardResultsSetPagination
from common.api.permissions import EndpointRBACPermission
from common.api.scopes import get_optional_request_restaurant


class AdminBaseReportView(APIView):
    permission_classes = [permissions.IsAuthenticated, EndpointRBACPermission]

    def get_restaurant(self):
        return get_optional_request_restaurant(self.request)

    def get_period(self) -> ReportPeriod:
        return SummaryReportFilters.from_request(self.request).period

    @staticmethod
    def get_filter_pairs(period: ReportPeriod, extra_filters: list[tuple[str, str]] | None = None) -> list[tuple[str, str]]:
        return build_report_filter_pairs(period, extra_filters)

    def resolve_filter_name(
        self,
        model,
        object_id: str,
        *,
        name_field: str = 'name',
        restaurant_lookup: str | None = 'restaurant',
    ) -> str:
        if not object_id:
            return ''
        queryset = model.objects.filter(pk=object_id)
        restaurant = self.get_restaurant()
        if restaurant is not None and restaurant_lookup:
            queryset = queryset.filter(**{restaurant_lookup: restaurant})
        return queryset.values_list(name_field, flat=True).first() or object_id


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


class ReceiptsReportView(AdminPaginatedReportView):
    def get(self, request):
        filters = ReceiptsReportFilters.from_request(request)
        queryset = filters.apply(get_receipts_report_queryset(self.get_restaurant(), filters.period))
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
        return build_excel_attachment(payload, filename=get_report_export_filename(REPORT_TITLE_SUMMARY, filters.period))


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
        return build_excel_attachment(payload, filename=get_report_export_filename(REPORT_TITLE_SALES, filters.period))


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
        return build_excel_attachment(payload, filename=get_report_export_filename(REPORT_TITLE_OPEN_CHECKS, filters.period))


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
        return build_excel_attachment(payload, filename=get_report_export_filename(REPORT_TITLE_RECEIPTS, filters.period))


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
        return build_excel_attachment(payload, filename=get_report_export_filename(REPORT_TITLE_TOP_ITEMS, filters.period))


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
        return build_excel_attachment(payload, filename=get_report_export_filename(REPORT_TITLE_TOP_STAFF, filters.period))


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
        return build_excel_attachment(payload, filename=get_report_export_filename(REPORT_TITLE_PAYMENT_BREAKDOWN, filters.period))


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
        return build_excel_attachment(payload, filename=get_report_export_filename(REPORT_TITLE_SHIFTS, filters.period))


__all__ = [
    'DashboardSummaryView',
    'OpenChecksReportExportView',
    'OpenChecksReportView',
    'PaymentBreakdownExportView',
    'PaymentBreakdownView',
    'ReceiptsReportExportView',
    'ReceiptsReportView',
    'SalesReportExportView',
    'SalesReportView',
    'ShiftReportExportView',
    'ShiftReportView',
    'SummaryReportExportView',
    'TopItemsReportExportView',
    'TopItemsReportView',
    'TopStaffReportExportView',
    'TopStaffReportView',
]
