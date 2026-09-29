from rest_framework.response import Response

from apps.reporting.helpers import (
    OpenChecksReportFilters,
    PaymentBreakdownReportFilters,
    ReceiptsReportFilters,
    SalesReportFilters,
    ShiftReportFilters,
    SummaryReportFilters,
    TopItemsReportFilters,
    TopStaffReportFilters,
)
from apps.reporting.services import (
    build_summary_charts_payload,
    build_summary_payload,
    get_open_checks_report_queryset,
    get_payment_breakdown_report_queryset,
    get_receipts_report_queryset,
    get_report_totals,
    get_sales_report_queryset,
    get_shift_report_queryset,
    get_top_items_report_queryset,
    get_top_items_report_totals,
    get_top_staff_report_queryset,
)

from .report_base import AdminBaseReportView, AdminPaginatedReportView
from .report_exports import (
    OpenChecksReportExportView,
    PaymentBreakdownExportView,
    ReceiptsReportExportView,
    SalesReportExportView,
    ShiftReportExportView,
    SummaryReportExportView,
    TopItemsReportExportView,
    TopStaffReportExportView,
)


class DashboardSummaryView(AdminBaseReportView):
    def get(self, request):
        filters = SummaryReportFilters.from_request(request)
        restaurant = self.get_restaurant()
        return Response({
            **build_summary_payload(restaurant, filters.period),
            **build_summary_charts_payload(restaurant, filters.period),
        })


class SalesReportView(AdminPaginatedReportView):
    def get(self, request):
        filters = SalesReportFilters.from_request(request)
        queryset = filters.apply(get_sales_report_queryset(self.get_restaurant(), filters.period, by_branch=self.get_restaurant() is None))
        totals = get_report_totals(queryset, 'count', 'total')
        page = self.paginate_queryset(queryset)
        return self.get_paginated_response(list(page), totals=totals)


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
        totals = get_report_totals(queryset, 'amount')
        page = self.paginate_queryset(queryset)
        return self.get_paginated_response(list(page), totals=totals)


class TopItemsReportView(AdminPaginatedReportView):
    def get(self, request):
        filters = TopItemsReportFilters.from_request(request)
        queryset = filters.apply(get_top_items_report_queryset(
            self.get_restaurant(), filters.period,
            by_branch=self.get_restaurant() is None, group_by=filters.group_by,
        ))
        totals = get_top_items_report_totals(queryset, group_by=filters.group_by)
        page = self.paginate_queryset(queryset)
        return self.get_paginated_response(list(page), totals=totals)


class TopStaffReportView(AdminPaginatedReportView):
    def get(self, request):
        filters = TopStaffReportFilters.from_request(request)
        queryset = filters.apply(get_top_staff_report_queryset(self.get_restaurant(), filters.period, by_branch=self.get_restaurant() is None))
        totals = get_report_totals(queryset, 'order_count', 'items_count', 'total_sales')
        page = self.paginate_queryset(queryset)
        return self.get_paginated_response(list(page), totals=totals)


class PaymentBreakdownView(AdminPaginatedReportView):
    def get(self, request):
        filters = PaymentBreakdownReportFilters.from_request(request)
        queryset = filters.apply(get_payment_breakdown_report_queryset(self.get_restaurant(), filters.period, by_branch=self.get_restaurant() is None))
        totals = get_report_totals(queryset, 'count', 'total')
        page = self.paginate_queryset(queryset)
        return self.get_paginated_response(list(page), totals=totals)


class ShiftReportView(AdminPaginatedReportView):
    def get(self, request):
        filters = ShiftReportFilters.from_request(request)
        queryset = filters.apply(get_shift_report_queryset(self.get_restaurant(), filters.period))
        totals = get_report_totals(
            queryset, 'opening_cash_amount', 'expected_closing_cash_amount',
            'actual_closing_cash_amount', 'cash_difference_amount', 'cash_total',
            'card_total', 'refund_total', 'expense_total', 'precheck_count', 'receipt_count',
        )
        page = self.paginate_queryset(queryset)
        return self.get_paginated_response(list(page), totals=totals)


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
