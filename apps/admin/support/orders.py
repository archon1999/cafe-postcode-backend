from dataclasses import dataclass

from django.db.models import Q, QuerySet

from apps.orders.models import Order, OrderItem, OrderItemNote, Payment, Receipt
from common.api.query_params import apply_ordering, get_ordering_query_param, get_str_list_query_param, get_str_query_param
from .scopes import filter_queryset_by_optional_scope

ORDER_STATUS_VALUES = {choice for choice, _label in Order.Status.choices}
ORDER_CHANNEL_VALUES = {choice for choice, _label in Order.Channel.choices}
ORDER_ITEM_STATUS_VALUES = {choice for choice, _label in OrderItem.Status.choices}
PAYMENT_STATUS_VALUES = {choice for choice, _label in Payment.Status.choices}
PAYMENT_METHOD_VALUES = {choice for choice, _label in Payment.Method.choices}
RECEIPT_STATUS_VALUES = {choice for choice, _label in Receipt.Status.choices}
RECEIPT_KIND_VALUES = {choice for choice, _label in Receipt.Kind.choices}
ORDER_ORDERING_FIELDS = {
    'orderNumber': 'order_number',
    'status': 'status',
    'channel': 'channel',
    'hallName': ('table_session__hall__name', 'order_number'),
    'tableName': ('table_session__table__name', 'order_number'),
    'openedByName': ('opened_by__full_name', 'order_number'),
    'cashierName': ('cashier__full_name', 'order_number'),
    'total': 'total',
    'createdAt': 'created_at',
    'closedAt': 'closed_at',
}
ORDER_ITEM_ORDERING_FIELDS = {
    'orderNumber': 'order__order_number',
    'catalogItemName': ('catalog_item__name', 'created_at'),
    'prepStationName': ('prep_station__name', 'created_at'),
    'createdByName': ('created_by__full_name', 'created_at'),
    'tableName': ('order__table_session__table__name', 'created_at'),
    'hallName': ('order__table_session__hall__name', 'created_at'),
    'quantity': 'quantity',
    'unitPrice': 'unit_price',
    'lineTotal': 'line_total',
    'status': 'status',
    'createdAt': 'created_at',
    'updatedAt': 'updated_at',
}
ORDER_ITEM_NOTE_ORDERING_FIELDS = {
    'orderNumber': 'order_item__order__order_number',
    'catalogItemName': ('order_item__catalog_item__name', 'created_at'),
    'tableName': ('order_item__order__table_session__table__name', 'created_at'),
    'createdAt': 'created_at',
    'updatedAt': 'updated_at',
}
PAYMENT_ORDERING_FIELDS = {
    'orderNumber': 'order__order_number',
    'cashDeskName': ('cash_desk__name', 'created_at'),
    'receivedByName': ('received_by__full_name', 'created_at'),
    'method': 'method',
    'amount': 'amount',
    'status': 'status',
    'paidAt': 'paid_at',
    'createdAt': 'created_at',
    'updatedAt': 'updated_at',
}
RECEIPT_ORDERING_FIELDS = {
    'orderNumber': 'order__order_number',
    'kind': 'kind',
    'status': 'status',
    'provider': 'provider',
    'createdAt': 'created_at',
    'updatedAt': 'updated_at',
}

def filter_order_queryset_by_scope(queryset, request, restaurant_lookup: str = 'restaurant'):
    return filter_queryset_by_optional_scope(queryset, request, restaurant_lookup=restaurant_lookup)


def admin_order_queryset(request) -> QuerySet[Order]:
    return (
        filter_order_queryset_by_scope(Order.objects.all(), request)
        .select_related(
            'table_session',
            'table_session__hall',
            'table_session__table',
            'distribution_point',
            'opened_by',
            'cashier',
        )
        .prefetch_related(
            'items__catalog_item',
            'items__prep_station',
            'items__created_by',
            'items__notes',
            'payments__cash_desk',
            'payments__cash_shift',
            'payments__received_by',
            'payments__refunds',
            'receipts__payment',
        )
        .order_by('-created_at')
    )


def admin_order_item_queryset(request) -> QuerySet[OrderItem]:
    return (
        filter_order_queryset_by_scope(OrderItem.objects.all(), request, 'order__restaurant')
        .select_related(
            'order',
            'order__table_session__hall',
            'order__table_session__table',
            'catalog_item',
            'prep_station',
            'created_by',
        )
        .prefetch_related('notes')
        .order_by('-created_at')
    )


def admin_order_item_note_queryset(request) -> QuerySet[OrderItemNote]:
    return (
        filter_order_queryset_by_scope(
            OrderItemNote.objects.all(),
            request,
            'order_item__order__restaurant',
        )
        .select_related(
            'order_item',
            'order_item__catalog_item',
            'order_item__order',
            'order_item__order__table_session__table',
        )
        .order_by('-created_at')
    )


def admin_payment_queryset(request) -> QuerySet[Payment]:
    return (
        filter_order_queryset_by_scope(Payment.objects.all(), request, 'order__restaurant')
        .select_related('order', 'cash_desk', 'cash_shift', 'received_by')
        .prefetch_related('refunds')
        .order_by('-created_at')
    )


def admin_receipt_queryset(request) -> QuerySet[Receipt]:
    return (
        filter_order_queryset_by_scope(Receipt.objects.all(), request, 'order__restaurant')
        .select_related('order', 'payment')
        .order_by('-created_at')
    )


@dataclass(frozen=True)
class OrderListFilters:
    search: str = ''
    statuses: tuple[str, ...] = ()
    channels: tuple[str, ...] = ()
    ordering: tuple[str, ...] = ()

    @classmethod
    def from_request(cls, request) -> 'OrderListFilters':
        query_params = request.query_params
        return cls(
            search=get_str_query_param(query_params, 'search'),
            statuses=tuple(get_str_list_query_param(query_params, 'status_in', allowed_values=ORDER_STATUS_VALUES)),
            channels=tuple(get_str_list_query_param(query_params, 'channel_in', allowed_values=ORDER_CHANNEL_VALUES)),
            ordering=get_ordering_query_param(query_params, ORDER_ORDERING_FIELDS),
        )

    def apply(self, queryset: QuerySet[Order]) -> QuerySet[Order]:
        if self.search:
            search_query = (
                Q(table_session__hall__name__icontains=self.search)
                | Q(table_session__table__name__icontains=self.search)
                | Q(opened_by__full_name__icontains=self.search)
                | Q(cashier__full_name__icontains=self.search)
            )
            if self.search.isdigit():
                search_query |= Q(order_number=int(self.search))
            queryset = queryset.filter(search_query)

        if self.statuses:
            queryset = queryset.filter(status__in=self.statuses)

        if self.channels:
            queryset = queryset.filter(channel__in=self.channels)

        return apply_ordering(queryset, self.ordering, default_ordering=('-created_at',))


@dataclass(frozen=True)
class OrderItemListFilters:
    search: str = ''
    statuses: tuple[str, ...] = ()
    ordering: tuple[str, ...] = ()

    @classmethod
    def from_request(cls, request) -> 'OrderItemListFilters':
        query_params = request.query_params
        return cls(
            search=get_str_query_param(query_params, 'search'),
            statuses=tuple(get_str_list_query_param(query_params, 'status_in', allowed_values=ORDER_ITEM_STATUS_VALUES)),
            ordering=get_ordering_query_param(query_params, ORDER_ITEM_ORDERING_FIELDS),
        )

    def apply(self, queryset: QuerySet[OrderItem]) -> QuerySet[OrderItem]:
        if self.search:
            search_query = (
                Q(catalog_item__name__icontains=self.search)
                | Q(prep_station__name__icontains=self.search)
                | Q(note__icontains=self.search)
                | Q(order__table_session__table__name__icontains=self.search)
            )
            if self.search.isdigit():
                search_query |= Q(order__order_number=int(self.search))
            queryset = queryset.filter(search_query)

        if self.statuses:
            queryset = queryset.filter(status__in=self.statuses)

        return apply_ordering(queryset, self.ordering, default_ordering=('-created_at',))


@dataclass(frozen=True)
class OrderItemNoteListFilters:
    search: str = ''
    ordering: tuple[str, ...] = ()

    @classmethod
    def from_request(cls, request) -> 'OrderItemNoteListFilters':
        return cls(
            search=get_str_query_param(request.query_params, 'search'),
            ordering=get_ordering_query_param(request.query_params, ORDER_ITEM_NOTE_ORDERING_FIELDS),
        )

    def apply(self, queryset: QuerySet[OrderItemNote]) -> QuerySet[OrderItemNote]:
        if not self.search:
            return apply_ordering(queryset, self.ordering, default_ordering=('-created_at',))

        search_query = (
            Q(body__icontains=self.search)
            | Q(order_item__catalog_item__name__icontains=self.search)
            | Q(order_item__order__table_session__table__name__icontains=self.search)
        )
        if self.search.isdigit():
            search_query |= Q(order_item__order__order_number=int(self.search))
        queryset = queryset.filter(search_query)
        return apply_ordering(queryset, self.ordering, default_ordering=('-created_at',))


@dataclass(frozen=True)
class PaymentListFilters:
    search: str = ''
    statuses: tuple[str, ...] = ()
    methods: tuple[str, ...] = ()
    ordering: tuple[str, ...] = ()

    @classmethod
    def from_request(cls, request) -> 'PaymentListFilters':
        query_params = request.query_params
        return cls(
            search=get_str_query_param(query_params, 'search'),
            statuses=tuple(get_str_list_query_param(query_params, 'status_in', allowed_values=PAYMENT_STATUS_VALUES)),
            methods=tuple(get_str_list_query_param(query_params, 'method_in', allowed_values=PAYMENT_METHOD_VALUES)),
            ordering=get_ordering_query_param(query_params, PAYMENT_ORDERING_FIELDS),
        )

    def apply(self, queryset: QuerySet[Payment]) -> QuerySet[Payment]:
        if self.search:
            search_query = (
                Q(external_ref__icontains=self.search)
                | Q(cash_desk__name__icontains=self.search)
                | Q(received_by__full_name__icontains=self.search)
            )
            if self.search.isdigit():
                search_query |= Q(order__order_number=int(self.search))
            queryset = queryset.filter(search_query)

        if self.statuses:
            queryset = queryset.filter(status__in=self.statuses)

        if self.methods:
            queryset = queryset.filter(method__in=self.methods)

        return apply_ordering(queryset, self.ordering, default_ordering=('-created_at',))


@dataclass(frozen=True)
class ReceiptListFilters:
    search: str = ''
    statuses: tuple[str, ...] = ()
    kinds: tuple[str, ...] = ()
    ordering: tuple[str, ...] = ()

    @classmethod
    def from_request(cls, request) -> 'ReceiptListFilters':
        query_params = request.query_params
        return cls(
            search=get_str_query_param(query_params, 'search'),
            statuses=tuple(get_str_list_query_param(query_params, 'status_in', allowed_values=RECEIPT_STATUS_VALUES)),
            kinds=tuple(get_str_list_query_param(query_params, 'kind_in', allowed_values=RECEIPT_KIND_VALUES)),
            ordering=get_ordering_query_param(query_params, RECEIPT_ORDERING_FIELDS),
        )

    def apply(self, queryset: QuerySet[Receipt]) -> QuerySet[Receipt]:
        if self.search:
            search_query = Q(provider__icontains=self.search)
            if self.search.isdigit():
                search_query |= Q(order__order_number=int(self.search))
            queryset = queryset.filter(search_query)

        if self.statuses:
            queryset = queryset.filter(status__in=self.statuses)

        if self.kinds:
            queryset = queryset.filter(kind__in=self.kinds)

        return apply_ordering(queryset, self.ordering, default_ordering=('-created_at',))


class AdminOrdersQuerysetMixin:
    def get_order_queryset(self) -> QuerySet[Order]:
        return admin_order_queryset(self.request)


class AdminOrderItemsQuerysetMixin:
    def get_order_item_queryset(self) -> QuerySet[OrderItem]:
        return admin_order_item_queryset(self.request)


class AdminOrderItemNotesQuerysetMixin:
    def get_order_item_note_queryset(self) -> QuerySet[OrderItemNote]:
        return admin_order_item_note_queryset(self.request)


class AdminPaymentsQuerysetMixin:
    def get_payment_queryset(self) -> QuerySet[Payment]:
        return admin_payment_queryset(self.request)


class AdminReceiptsQuerysetMixin:
    def get_receipt_queryset(self) -> QuerySet[Receipt]:
        return admin_receipt_queryset(self.request)
