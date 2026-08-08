from dataclasses import dataclass

from django.db.models import Q, QuerySet

from apps.kitchen.models import KitchenTicket
from common.api.query_params import (
    apply_ordering,
    get_bool_query_param,
    get_ordering_query_param,
    get_str_list_query_param,
    get_str_query_param,
)
from common.api.scope_filters import filter_queryset_by_optional_scope

KITCHEN_TICKET_STATUS_VALUES = {
    choice for choice, _label in KitchenTicket.Status.choices
}
KITCHEN_TICKET_ROUTE_MODE_VALUES = {
    choice for choice, _label in KitchenTicket.RouteMode.choices
}
KITCHEN_TICKET_ORDERING_FIELDS = {
    "orderNumber": "order__order_number",
    "prepStationName": ("prep_station__name", "created_at"),
    "status": "status",
    "routedVia": "routed_via",
    "isPrinted": "is_printed",
    "hallName": ("order__table_session__hall__name", "created_at"),
    "tableName": ("order__table_session__table__name", "created_at"),
    "waiterName": ("order__opened_by__full_name", "created_at"),
    "completedAt": "completed_at",
    "createdAt": "created_at",
}


def admin_kitchen_ticket_queryset(request) -> QuerySet:
    return (
        filter_queryset_by_optional_scope(KitchenTicket.objects.all(), request)
        .select_related(
            "restaurant",
            "prep_station",
            "order__opened_by",
            "order__table_session__hall",
            "order__table_session__table",
        )
        .prefetch_related("lines__order_item__catalog_item", "lines__order_item__prep_station")
        .order_by("-created_at")
    )


@dataclass(frozen=True)
class KitchenTicketListFilters:
    search: str = ""
    statuses: tuple[str, ...] = ()
    prep_station_ids: tuple[str, ...] = ()
    routed_via_values: tuple[str, ...] = ()
    is_printed: bool | None = None
    ordering: tuple[str, ...] = ()

    @classmethod
    def from_request(cls, request) -> "KitchenTicketListFilters":
        query_params = request.query_params
        prep_station_ids = list(
            get_str_list_query_param(query_params, "prep_station_id_in")
        )
        single_prep_station_id = (query_params.get("prep_station_id") or "").strip()
        if single_prep_station_id:
            prep_station_ids.append(single_prep_station_id)

        statuses = list(
            get_str_list_query_param(
                query_params, "status_in", allowed_values=KITCHEN_TICKET_STATUS_VALUES
            )
        )
        single_status = (query_params.get("status") or "").strip()
        if single_status in KITCHEN_TICKET_STATUS_VALUES:
            statuses.append(single_status)

        routed_via_values = list(
            get_str_list_query_param(
                query_params,
                "routed_via_in",
                allowed_values=KITCHEN_TICKET_ROUTE_MODE_VALUES,
            )
        )
        single_routed_via = (query_params.get("routed_via") or "").strip()
        if single_routed_via in KITCHEN_TICKET_ROUTE_MODE_VALUES:
            routed_via_values.append(single_routed_via)

        return cls(
            search=get_str_query_param(query_params, "search"),
            statuses=tuple(dict.fromkeys(statuses)),
            prep_station_ids=tuple(dict.fromkeys(prep_station_ids)),
            routed_via_values=tuple(dict.fromkeys(routed_via_values)),
            is_printed=get_bool_query_param(query_params, "is_printed"),
            ordering=get_ordering_query_param(
                query_params, KITCHEN_TICKET_ORDERING_FIELDS
            ),
        )

    def apply(self, queryset: QuerySet) -> QuerySet:
        if self.search:
            search_query = (
                Q(prep_station__name__icontains=self.search)
                | Q(order__table_session__hall__name__icontains=self.search)
                | Q(order__table_session__table__name__icontains=self.search)
                | Q(order__opened_by__full_name__icontains=self.search)
            )
            if self.search.isdigit():
                search_query |= Q(order__order_number=int(self.search))
            queryset = queryset.filter(search_query)
        if self.statuses:
            queryset = queryset.filter(status__in=self.statuses)
        if self.prep_station_ids:
            queryset = queryset.filter(prep_station_id__in=self.prep_station_ids)
        if self.routed_via_values:
            queryset = queryset.filter(routed_via__in=self.routed_via_values)
        if self.is_printed is not None:
            queryset = queryset.filter(is_printed=self.is_printed)
        return apply_ordering(
            queryset, self.ordering, default_ordering=("-created_at",)
        )
