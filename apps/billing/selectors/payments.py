from dataclasses import dataclass

from django.db.models import Q, QuerySet

from apps.billing.helpers import get_payment_model, get_receipt_model
from common.api.query_params import apply_ordering, get_ordering_query_param, get_str_list_query_param, get_str_query_param
from common.api.scope_filters import filter_queryset_by_optional_scope

Payment = get_payment_model()
Receipt = get_receipt_model()

PAYMENT_STATUS_VALUES = {choice for choice, _label in Payment.Status.choices}
PAYMENT_METHOD_VALUES = {choice for choice, _label in Payment.Method.choices}
RECEIPT_STATUS_VALUES = {choice for choice, _label in Receipt.Status.choices}
RECEIPT_KIND_VALUES = {choice for choice, _label in Receipt.Kind.choices}
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


def admin_payment_queryset(request) -> QuerySet:
    return (
        filter_queryset_by_optional_scope(Payment.objects.all(), request, restaurant_lookup='order__restaurant')
        .select_related('order', 'cash_desk', 'cash_shift', 'received_by')
        .prefetch_related('refunds')
        .order_by('-created_at')
    )


def admin_receipt_queryset(request) -> QuerySet:
    return (
        filter_queryset_by_optional_scope(Receipt.objects.all(), request, restaurant_lookup='order__restaurant')
        .select_related('order', 'payment')
        .order_by('-created_at')
    )


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

    def apply(self, queryset: QuerySet) -> QuerySet:
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

    def apply(self, queryset: QuerySet) -> QuerySet:
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
