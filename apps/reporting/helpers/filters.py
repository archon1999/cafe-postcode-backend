from dataclasses import dataclass

from django.db.models import Q, QuerySet
from django.http import HttpResponse
from django.utils.http import content_disposition_header

from apps.reporting.services import ORDER_STATUS_VALUES, PAYMENT_METHOD_VALUES, ReportPeriod, SHIFT_STATUS_VALUES, get_report_period
from common.api.query_params import apply_ordering, get_ordering_query_param, get_str_list_query_param, get_str_query_param

SALES_ORDERING_FIELDS = {
    'method': 'method',
    'count': 'count',
    'total': 'total',
}
OPEN_CHECKS_ORDERING_FIELDS = {
    'orderNumber': 'order_number',
    'status': 'status',
    'hallName': ('hall_name', 'order_number'),
    'tableName': ('table_name', 'order_number'),
    'total': 'total',
    'createdAt': 'created_at',
}
TOP_ITEMS_ORDERING_FIELDS = {
    'catalogItemName': ('catalog_item_name', 'quantity'),
    'categoryName': ('category_name', 'catalog_item_name'),
    'quantity': 'quantity',
    'revenue': 'revenue',
}
TOP_STAFF_ORDERING_FIELDS = {
    'staffName': ('staff_name', 'total_sales'),
    'orderCount': 'order_count',
    'itemsCount': 'items_count',
    'totalSales': 'total_sales',
}
PAYMENT_BREAKDOWN_ORDERING_FIELDS = {
    'method': 'method',
    'count': 'count',
    'total': 'total',
}
SHIFT_ORDERING_FIELDS = {
    'cashierName': ('cashier_name', 'opened_at'),
    'cashDeskName': ('cash_desk_name', 'opened_at'),
    'status': 'status',
    'openedAt': 'opened_at',
    'closedAt': 'closed_at',
    'openingCashAmount': 'opening_cash_amount',
    'cashTotal': 'cash_total',
    'refundTotal': 'refund_total',
    'precheckCount': 'precheck_count',
    'receiptCount': 'receipt_count',
    'difference': 'cash_difference_amount',
}
RECEIPTS_ORDERING_FIELDS = {
    'orderNumber': 'order_number',
    'kind': 'kind',
    'status': 'status',
    'amount': 'amount',
    'paymentMethod': 'payment_method',
    'cashierName': ('cashier_name', 'created_at'),
    'cashDeskName': ('cash_desk_name', 'created_at'),
    'createdAt': 'created_at',
}


def get_choice_query_param(query_params, key: str, allowed_values: set[str], *, alias: str | None = None) -> str:
    aliases = (alias,) if alias else ()
    value = get_str_query_param(query_params, key, aliases=aliases)
    if not value or value not in allowed_values:
        return ''
    return value


def build_excel_attachment(payload: bytes, *, filename: str) -> HttpResponse:
    response = HttpResponse(
        payload,
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    response['Content-Disposition'] = content_disposition_header(True, filename)
    return response


@dataclass(frozen=True)
class SummaryReportFilters:
    period: ReportPeriod

    @classmethod
    def from_request(cls, request) -> 'SummaryReportFilters':
        return cls(period=get_report_period(request.query_params))


@dataclass(frozen=True)
class SalesReportFilters:
    period: ReportPeriod
    search: str = ''
    payment_method: str = ''
    ordering: tuple[str, ...] = ()

    @classmethod
    def from_request(cls, request) -> 'SalesReportFilters':
        query_params = request.query_params
        return cls(
            period=get_report_period(query_params),
            search=get_str_query_param(query_params, 'search'),
            payment_method=get_choice_query_param(
                query_params,
                'payment_method',
                set(PAYMENT_METHOD_VALUES),
                alias='paymentMethod',
            ),
            ordering=get_ordering_query_param(query_params, SALES_ORDERING_FIELDS),
        )

    def apply(self, queryset: QuerySet) -> QuerySet:
        if self.search:
            queryset = queryset.filter(method__icontains=self.search)
        if self.payment_method:
            queryset = queryset.filter(method=self.payment_method)
        return apply_ordering(queryset, self.ordering, default_ordering=('method',))


@dataclass(frozen=True)
class OpenChecksReportFilters:
    period: ReportPeriod
    search: str = ''
    status: str = ''
    hall_id: str = ''
    ordering: tuple[str, ...] = ()

    @classmethod
    def from_request(cls, request) -> 'OpenChecksReportFilters':
        query_params = request.query_params
        return cls(
            period=get_report_period(query_params),
            search=get_str_query_param(query_params, 'search'),
            status=get_choice_query_param(query_params, 'status', set(ORDER_STATUS_VALUES)),
            hall_id=get_str_query_param(query_params, 'hall_id', aliases=('hallId',)),
            ordering=get_ordering_query_param(query_params, OPEN_CHECKS_ORDERING_FIELDS),
        )

    def apply(self, queryset: QuerySet) -> QuerySet:
        if self.search:
            search_query = Q(hall_name__icontains=self.search) | Q(table_name__icontains=self.search)
            if self.search.isdigit():
                search_query |= Q(order_number=int(self.search))
            queryset = queryset.filter(search_query)
        if self.status:
            queryset = queryset.filter(status=self.status)
        if self.hall_id:
            queryset = queryset.filter(hall_id=self.hall_id)
        return apply_ordering(queryset, self.ordering, default_ordering=('-created_at',))


@dataclass(frozen=True)
class ReceiptsReportFilters:
    period: ReportPeriod
    search: str = ''
    kind: str = ''
    status: str = ''
    ordering: tuple[str, ...] = ()

    @classmethod
    def from_request(cls, request) -> 'ReceiptsReportFilters':
        query_params = request.query_params
        return cls(
            period=get_report_period(query_params),
            search=get_str_query_param(query_params, 'search'),
            kind=get_choice_query_param(
                query_params,
                'receipt_kind',
                {'plain', 'fiscal'},
                alias='receiptKind',
            ),
            status=get_choice_query_param(
                query_params,
                'status',
                {'created', 'sent', 'failed'},
            ),
            ordering=get_ordering_query_param(query_params, RECEIPTS_ORDERING_FIELDS),
        )

    def apply(self, queryset: QuerySet) -> QuerySet:
        if self.search:
            search_query = (
                Q(cashier_name__icontains=self.search)
                | Q(cash_desk_name__icontains=self.search)
                | Q(payment_method__icontains=self.search)
            )
            normalized_search = self.search.lstrip('#')
            if normalized_search.isdigit():
                search_query |= Q(order_number=int(normalized_search))
            queryset = queryset.filter(search_query)
        if self.kind:
            queryset = queryset.filter(kind=self.kind)
        if self.status:
            queryset = queryset.filter(status=self.status)
        return apply_ordering(queryset, self.ordering, default_ordering=('-created_at',))


@dataclass(frozen=True)
class TopItemsReportFilters:
    period: ReportPeriod
    search: str = ''
    category_id: str = ''
    ordering: tuple[str, ...] = ()

    @classmethod
    def from_request(cls, request) -> 'TopItemsReportFilters':
        query_params = request.query_params
        return cls(
            period=get_report_period(query_params),
            search=get_str_query_param(query_params, 'search'),
            category_id=get_str_query_param(query_params, 'category_id', aliases=('categoryId',)),
            ordering=get_ordering_query_param(query_params, TOP_ITEMS_ORDERING_FIELDS),
        )

    def apply(self, queryset: QuerySet) -> QuerySet:
        if self.search:
            queryset = queryset.filter(
                Q(catalog_item_name__icontains=self.search) | Q(category_name__icontains=self.search)
            )
        if self.category_id:
            queryset = queryset.filter(category_id=self.category_id)
        return apply_ordering(queryset, self.ordering, default_ordering=('-quantity', '-revenue'))


@dataclass(frozen=True)
class TopStaffReportFilters:
    period: ReportPeriod
    search: str = ''
    ordering: tuple[str, ...] = ()

    @classmethod
    def from_request(cls, request) -> 'TopStaffReportFilters':
        query_params = request.query_params
        return cls(
            period=get_report_period(query_params),
            search=get_str_query_param(query_params, 'search'),
            ordering=get_ordering_query_param(query_params, TOP_STAFF_ORDERING_FIELDS),
        )

    def apply(self, queryset: QuerySet) -> QuerySet:
        if self.search:
            queryset = queryset.filter(staff_name__icontains=self.search)
        return apply_ordering(queryset, self.ordering, default_ordering=('-total_sales', '-order_count'))


@dataclass(frozen=True)
class PaymentBreakdownReportFilters:
    period: ReportPeriod
    search: str = ''
    payment_method: str = ''
    ordering: tuple[str, ...] = ()

    @classmethod
    def from_request(cls, request) -> 'PaymentBreakdownReportFilters':
        query_params = request.query_params
        return cls(
            period=get_report_period(query_params),
            search=get_str_query_param(query_params, 'search'),
            payment_method=get_choice_query_param(
                query_params,
                'payment_method',
                set(PAYMENT_METHOD_VALUES),
                alias='paymentMethod',
            ),
            ordering=get_ordering_query_param(query_params, PAYMENT_BREAKDOWN_ORDERING_FIELDS),
        )

    def apply(self, queryset: QuerySet) -> QuerySet:
        if self.search:
            queryset = queryset.filter(method__icontains=self.search)
        if self.payment_method:
            queryset = queryset.filter(method=self.payment_method)
        return apply_ordering(queryset, self.ordering, default_ordering=('-total', 'method'))


@dataclass(frozen=True)
class ShiftReportFilters:
    period: ReportPeriod
    search: str = ''
    cash_desk_id: str = ''
    cashier_id: str = ''
    statuses: tuple[str, ...] = ()
    difference_only: bool = False
    ordering: tuple[str, ...] = ()

    @classmethod
    def from_request(cls, request) -> 'ShiftReportFilters':
        query_params = request.query_params
        difference_raw = get_str_query_param(query_params, 'difference_only', aliases=('differenceOnly',))
        statuses = tuple(get_str_list_query_param(query_params, 'status_in', allowed_values=SHIFT_STATUS_VALUES))
        if not statuses:
            single_status = get_choice_query_param(query_params, 'status', set(SHIFT_STATUS_VALUES), alias='statusIn')
            statuses = (single_status,) if single_status else ()
        return cls(
            period=get_report_period(query_params),
            search=get_str_query_param(query_params, 'search'),
            cash_desk_id=get_str_query_param(query_params, 'cash_desk_id', aliases=('cashDeskId',)),
            cashier_id=get_str_query_param(query_params, 'cashier_id', aliases=('cashierId',)),
            statuses=statuses,
            difference_only=difference_raw.lower() in {'1', 'true', 'yes'} if difference_raw else False,
            ordering=get_ordering_query_param(query_params, SHIFT_ORDERING_FIELDS),
        )

    def apply(self, queryset: QuerySet) -> QuerySet:
        if self.search:
            queryset = queryset.filter(Q(cashier_name__icontains=self.search) | Q(cash_desk_name__icontains=self.search))
        if self.cash_desk_id:
            queryset = queryset.filter(cash_desk_id=self.cash_desk_id)
        if self.cashier_id:
            queryset = queryset.filter(cashier_id=self.cashier_id)
        if self.statuses:
            queryset = queryset.filter(status__in=self.statuses)
        if self.difference_only:
            queryset = queryset.exclude(cash_difference_amount=0)
        return apply_ordering(queryset, self.ordering, default_ordering=('-opened_at',))
