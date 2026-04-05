from dataclasses import dataclass

from django.db.models import Prefetch, Q, QuerySet

from apps.floor.models import DiningTable, Hall, TableSession, ZoneOrCabin
from common.api.query_params import (
    apply_ordering,
    get_bool_query_param,
    get_ordering_query_param,
    get_str_list_query_param,
    get_str_query_param,
)
from common.api.scope_filters import filter_queryset_by_optional_restaurant

HALL_ORDERING_FIELDS = {
    'name': 'name',
    'description': 'description',
    'zoneOrCabinName': ('zone_or_cabin__sort_order', 'zone_or_cabin__name', 'name'),
    'sortOrder': 'sort_order',
    'isActive': 'is_active',
}
DINING_TABLE_ORDERING_FIELDS = {
    'name': 'name',
    'tableNumber': 'table_number',
    'hallName': ('hall__name', 'table_number'),
    'zoneName': ('zone__name', 'table_number'),
    'seatCount': 'seat_count',
    'shape': 'shape',
    'status': 'status',
}
ZONE_ORDERING_FIELDS = {
    'name': 'name',
    'sortOrder': 'sort_order',
    'isActive': 'is_active',
}
TABLE_SESSION_ORDERING_FIELDS = {
    'tableName': ('table__name', 'created_at'),
    'hallName': ('hall__name', 'created_at'),
    'openedByName': ('opened_by__full_name', 'created_at'),
    'assignedWaiterName': ('assigned_waiter__full_name', 'created_at'),
    'guestCount': 'guest_count',
    'status': 'status',
    'createdAt': 'created_at',
}


def hall_constructor_queryset(request) -> QuerySet:
    table_queryset = DiningTable.objects.order_by('table_number', 'name')
    queryset = Hall.objects.select_related('zone_or_cabin').prefetch_related(Prefetch('tables', queryset=table_queryset))
    return filter_queryset_by_optional_restaurant(queryset, request, lookup='zone_or_cabin__restaurant')


@dataclass(frozen=True)
class HallListFilters:
    search: str = ''
    is_active: bool | None = None
    ordering: tuple[str, ...] = ()

    @classmethod
    def from_request(cls, request) -> 'HallListFilters':
        query_params = request.query_params
        return cls(
            search=get_str_query_param(query_params, 'search'),
            is_active=get_bool_query_param(query_params, 'is_active'),
            ordering=get_ordering_query_param(query_params, HALL_ORDERING_FIELDS),
        )

    def apply(self, queryset: QuerySet) -> QuerySet:
        if self.search:
            queryset = queryset.filter(
                Q(name__icontains=self.search)
                | Q(description__icontains=self.search)
                | Q(zone_or_cabin__name__icontains=self.search)
            )
        if self.is_active is not None:
            queryset = queryset.filter(is_active=self.is_active)
        return apply_ordering(queryset.distinct(), self.ordering, default_ordering=('sort_order', 'name'))


@dataclass(frozen=True)
class DiningTableListFilters:
    search: str = ''
    hall_ids: tuple[str, ...] = ()
    shapes: tuple[str, ...] = ()
    statuses: tuple[str, ...] = ()
    ordering: tuple[str, ...] = ()

    @classmethod
    def from_request(cls, request) -> 'DiningTableListFilters':
        query_params = request.query_params
        return cls(
            search=get_str_query_param(query_params, 'search'),
            hall_ids=tuple(get_str_list_query_param(query_params, 'hall_id_in')),
            shapes=tuple(get_str_list_query_param(query_params, 'shape_in')),
            statuses=tuple(get_str_list_query_param(query_params, 'status_in')),
            ordering=get_ordering_query_param(query_params, DINING_TABLE_ORDERING_FIELDS),
        )

    def apply(self, queryset: QuerySet) -> QuerySet:
        if self.search:
            search_query = (
                Q(name__icontains=self.search)
                | Q(code__icontains=self.search)
                | Q(hall__name__icontains=self.search)
                | Q(zone__name__icontains=self.search)
            )
            if self.search.isdigit():
                search_query |= Q(table_number=int(self.search))
            queryset = queryset.filter(search_query)
        if self.hall_ids:
            queryset = queryset.filter(hall_id__in=self.hall_ids)
        if self.shapes:
            queryset = queryset.filter(shape__in=self.shapes)
        if self.statuses:
            queryset = queryset.filter(status__in=self.statuses)
        return apply_ordering(queryset.distinct(), self.ordering, default_ordering=('table_number', 'name'))


@dataclass(frozen=True)
class ZoneListFilters:
    search: str = ''
    is_active: bool | None = None
    ordering: tuple[str, ...] = ()

    @classmethod
    def from_request(cls, request) -> 'ZoneListFilters':
        query_params = request.query_params
        return cls(
            search=get_str_query_param(query_params, 'search'),
            is_active=get_bool_query_param(query_params, 'is_active'),
            ordering=get_ordering_query_param(query_params, ZONE_ORDERING_FIELDS),
        )

    def apply(self, queryset: QuerySet) -> QuerySet:
        if self.search:
            queryset = queryset.filter(Q(name__icontains=self.search))
        if self.is_active is not None:
            queryset = queryset.filter(is_active=self.is_active)
        return apply_ordering(queryset.distinct(), self.ordering, default_ordering=('sort_order', 'name'))


@dataclass(frozen=True)
class TableSessionListFilters:
    search: str = ''
    hall_ids: tuple[str, ...] = ()
    statuses: tuple[str, ...] = ()
    ordering: tuple[str, ...] = ()

    @classmethod
    def from_request(cls, request) -> 'TableSessionListFilters':
        query_params = request.query_params
        return cls(
            search=get_str_query_param(query_params, 'search'),
            hall_ids=tuple(get_str_list_query_param(query_params, 'hall_id_in')),
            statuses=tuple(get_str_list_query_param(query_params, 'status_in')),
            ordering=get_ordering_query_param(query_params, TABLE_SESSION_ORDERING_FIELDS),
        )

    def apply(self, queryset: QuerySet) -> QuerySet:
        if self.search:
            queryset = queryset.filter(
                Q(table__name__icontains=self.search)
                | Q(hall__name__icontains=self.search)
                | Q(opened_by__full_name__icontains=self.search)
                | Q(assigned_waiter__full_name__icontains=self.search)
                | Q(note__icontains=self.search)
            )
        if self.hall_ids:
            queryset = queryset.filter(hall_id__in=self.hall_ids)
        if self.statuses:
            queryset = queryset.filter(status__in=self.statuses)
        return apply_ordering(queryset, self.ordering, default_ordering=('-created_at',))
