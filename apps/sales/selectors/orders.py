from dataclasses import dataclass

from django.db.models import Prefetch, Q, QuerySet

from apps.billing.helpers import get_payment_model, get_payment_refund_model
from apps.sales.helpers import (
    get_order_item_model,
    get_order_item_note_model,
    get_order_model,
)
from apps.sales.models import OrderItemModifier
from common.api.query_params import (
    apply_ordering,
    get_ordering_query_param,
    get_str_list_query_param,
    get_str_query_param,
)
from common.api.scope_filters import filter_queryset_by_optional_scope

Order = get_order_model()
OrderItem = get_order_item_model()
OrderItemNote = get_order_item_note_model()
Payment = get_payment_model()
PaymentRefund = get_payment_refund_model()

ORDER_STATUS_VALUES = {choice for choice, _label in Order.Status.choices}
ORDER_CHANNEL_VALUES = {choice for choice, _label in Order.Channel.choices}
ORDER_ITEM_STATUS_VALUES = {choice for choice, _label in OrderItem.Status.choices}
ORDER_ORDERING_FIELDS = {
    "orderNumber": "order_number",
    "status": "status",
    "channel": "channel",
    "hallName": ("table_session__hall__name", "order_number"),
    "tableName": ("table_session__table__name", "order_number"),
    "openedByName": ("opened_by__full_name", "order_number"),
    "cashierName": ("cashier__full_name", "order_number"),
    "total": "total",
    "createdAt": "created_at",
    "closedAt": "closed_at",
}
ORDER_ITEM_ORDERING_FIELDS = {
    "orderNumber": "order__order_number",
    "catalogItemName": ("catalog_item__name", "created_at"),
    "prepStationName": ("prep_station__name", "created_at"),
    "createdByName": ("created_by__full_name", "created_at"),
    "tableName": ("order__table_session__table__name", "created_at"),
    "hallName": ("order__table_session__hall__name", "created_at"),
    "quantity": "quantity",
    "unitPrice": "unit_price",
    "lineTotal": "line_total",
    "status": "status",
    "createdAt": "created_at",
    "updatedAt": "updated_at",
}
ORDER_ITEM_NOTE_ORDERING_FIELDS = {
    "orderNumber": "order_item__order__order_number",
    "catalogItemName": ("order_item__catalog_item__name", "created_at"),
    "tableName": ("order_item__order__table_session__table__name", "created_at"),
    "createdAt": "created_at",
    "updatedAt": "updated_at",
}


def filter_order_queryset_by_scope(
    queryset, request, restaurant_lookup: str = "restaurant"
):
    return filter_queryset_by_optional_scope(
        queryset, request, restaurant_lookup=restaurant_lookup
    )


def pos_order_queryset(queryset: QuerySet | None = None) -> QuerySet:
    """Load the complete relation graph consumed by the POS order serializer."""
    if queryset is None:
        queryset = Order.objects.all()

    item_queryset = (
        OrderItem.objects.select_related(
            "catalog_item",
            "prep_station",
            "kitchen_ticket_line__ticket",
        )
        .prefetch_related(
            "markings",
            Prefetch(
                "modifiers",
                queryset=OrderItemModifier.objects.select_related(
                    "modifier_option__group"
                ),
            ),
        )
    )
    payment_queryset = Payment.objects.prefetch_related(
        Prefetch(
            "refunds",
            queryset=PaymentRefund.objects.select_related("refunded_by"),
        )
    )

    return queryset.select_related(
        "restaurant",
        "table_session",
        "table_session__hall",
        "table_session__table",
        "opened_by",
        "cashier",
    ).prefetch_related(
        Prefetch("items", queryset=item_queryset),
        Prefetch("payments", queryset=payment_queryset),
        "receipts",
    )


def admin_order_queryset(request) -> QuerySet:
    return (
        filter_order_queryset_by_scope(Order.objects.all(), request)
        .select_related(
            "restaurant",
            "table_session",
            "table_session__hall",
            "table_session__table",
            "distribution_point",
            "opened_by",
            "cashier",
            "total_overridden_by",
        )
        .prefetch_related(
            "items__catalog_item",
            "items__prep_station",
            "items__created_by",
            "items__notes",
            "payments__cash_desk",
            "payments__cash_shift",
            "payments__received_by",
            "payments__refunds",
            "receipts__payment",
        )
        .order_by("-created_at")
    )


def admin_order_detail_queryset(request) -> QuerySet:
    return admin_order_queryset(request).prefetch_related(
        "receipts__print_document__template_version"
    )


def admin_order_item_queryset(request) -> QuerySet:
    return (
        filter_order_queryset_by_scope(
            OrderItem.objects.all(), request, "order__restaurant"
        )
        .select_related(
            "order",
            "order__restaurant",
            "order__table_session__hall",
            "order__table_session__table",
            "catalog_item",
            "prep_station",
            "created_by",
        )
        .prefetch_related("notes")
        .order_by("-created_at")
    )


def admin_order_item_note_queryset(request) -> QuerySet:
    return (
        filter_order_queryset_by_scope(
            OrderItemNote.objects.all(),
            request,
            "order_item__order__restaurant",
        )
        .select_related(
            "order_item",
            "order_item__catalog_item",
            "order_item__order",
            "order_item__order__restaurant",
            "order_item__order__table_session__table",
        )
        .order_by("-created_at")
    )


@dataclass(frozen=True)
class OrderListFilters:
    search: str = ""
    statuses: tuple[str, ...] = ()
    channels: tuple[str, ...] = ()
    ordering: tuple[str, ...] = ()

    @classmethod
    def from_request(cls, request) -> "OrderListFilters":
        query_params = request.query_params
        return cls(
            search=get_str_query_param(query_params, "search"),
            statuses=tuple(
                get_str_list_query_param(
                    query_params, "status_in", allowed_values=ORDER_STATUS_VALUES
                )
            ),
            channels=tuple(
                get_str_list_query_param(
                    query_params, "channel_in", allowed_values=ORDER_CHANNEL_VALUES
                )
            ),
            ordering=get_ordering_query_param(query_params, ORDER_ORDERING_FIELDS),
        )

    def apply(self, queryset: QuerySet) -> QuerySet:
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

        return apply_ordering(
            queryset, self.ordering, default_ordering=("-created_at",)
        )


@dataclass(frozen=True)
class OrderItemListFilters:
    search: str = ""
    statuses: tuple[str, ...] = ()
    ordering: tuple[str, ...] = ()

    @classmethod
    def from_request(cls, request) -> "OrderItemListFilters":
        query_params = request.query_params
        return cls(
            search=get_str_query_param(query_params, "search"),
            statuses=tuple(
                get_str_list_query_param(
                    query_params, "status_in", allowed_values=ORDER_ITEM_STATUS_VALUES
                )
            ),
            ordering=get_ordering_query_param(query_params, ORDER_ITEM_ORDERING_FIELDS),
        )

    def apply(self, queryset: QuerySet) -> QuerySet:
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

        return apply_ordering(
            queryset, self.ordering, default_ordering=("-created_at",)
        )


@dataclass(frozen=True)
class OrderItemNoteListFilters:
    search: str = ""
    ordering: tuple[str, ...] = ()

    @classmethod
    def from_request(cls, request) -> "OrderItemNoteListFilters":
        return cls(
            search=get_str_query_param(request.query_params, "search"),
            ordering=get_ordering_query_param(
                request.query_params, ORDER_ITEM_NOTE_ORDERING_FIELDS
            ),
        )

    def apply(self, queryset: QuerySet) -> QuerySet:
        if not self.search:
            return apply_ordering(
                queryset, self.ordering, default_ordering=("-created_at",)
            )

        search_query = (
            Q(body__icontains=self.search)
            | Q(order_item__catalog_item__name__icontains=self.search)
            | Q(order_item__order__table_session__table__name__icontains=self.search)
        )
        if self.search.isdigit():
            search_query |= Q(order_item__order__order_number=int(self.search))
        queryset = queryset.filter(search_query)
        return apply_ordering(
            queryset, self.ordering, default_ordering=("-created_at",)
        )
