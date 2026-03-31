from dataclasses import dataclass

from django.db.models import Q, QuerySet

from apps.floor.models import DiningTable, Hall, TableSession, ZoneOrCabin
from apps.organizations.models import CashDesk, Device, DistributionPoint, FeatureConfig, PrepStation, Restaurant
from common.api.permissions import IsAdmin
from common.api.query_params import (
    apply_ordering,
    get_bool_query_param,
    get_ordering_query_param,
    get_str_list_query_param,
    get_str_query_param,
)
from .scopes import filter_queryset_by_optional_restaurant

FEATURE_CONFIG_ORDERING_FIELDS = {
    'restaurantName': 'restaurant__name',
    'orderEntryMode': 'order_entry_mode',
    'kitchenMode': 'kitchen_mode',
}
HALL_ORDERING_FIELDS = {
    'name': 'name',
    'description': 'description',
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
    'hallName': ('hall__name', 'name'),
    'isPrivate': 'is_private',
    'sortOrder': 'sort_order',
    'isActive': 'is_active',
}
PREP_STATION_ORDERING_FIELDS = {
    'name': 'name',
    'code': 'code',
    'kind': 'kind',
    'isActive': 'is_active',
}
CASH_DESK_ORDERING_FIELDS = {
    'name': 'name',
    'location': 'location',
    'isActive': 'is_active',
}
DISTRIBUTION_POINT_ORDERING_FIELDS = {
    'name': 'name',
    'kind': 'kind',
    'assignedHallName': ('assigned_hall__name', 'name'),
    'integrationChannel': 'integration_channel',
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
DEVICE_ORDERING_FIELDS = {
    'name': 'name',
    'code': 'code',
    'mode': 'mode',
    'primaryHallName': ('primary_hall__name', 'name'),
    'isActive': 'is_active',
}
RESTAURANT_ORDERING_FIELDS = {
    'name': 'name',
    'slug': 'slug',
    'legalName': 'legal_name',
    'phone': 'phone',
    'currency': 'currency',
    'isActive': 'is_active',
}

def filter_constructor_queryset_by_restaurant(queryset, request, lookup: str = 'restaurant'):
    return filter_queryset_by_optional_restaurant(queryset, request, lookup=lookup)


@dataclass(frozen=True)
class FeatureConfigListFilters:
    search: str = ''
    order_entry_modes: tuple[str, ...] = ()
    kitchen_modes: tuple[str, ...] = ()
    ordering: tuple[str, ...] = ()

    @classmethod
    def from_request(cls, request) -> 'FeatureConfigListFilters':
        query_params = request.query_params
        return cls(
            search=get_str_query_param(query_params, 'search'),
            order_entry_modes=tuple(get_str_list_query_param(query_params, 'order_entry_mode_in')),
            kitchen_modes=tuple(get_str_list_query_param(query_params, 'kitchen_mode_in')),
            ordering=get_ordering_query_param(query_params, FEATURE_CONFIG_ORDERING_FIELDS),
        )

    def apply(self, queryset: QuerySet[FeatureConfig]) -> QuerySet[FeatureConfig]:
        if self.search:
            queryset = queryset.filter(
                Q(restaurant__name__icontains=self.search)
                | Q(enabled_modules__icontains=self.search)
                | Q(enabled_roles__icontains=self.search)
            )
        if self.order_entry_modes:
            queryset = queryset.filter(order_entry_mode__in=self.order_entry_modes)
        if self.kitchen_modes:
            queryset = queryset.filter(kitchen_mode__in=self.kitchen_modes)
        return apply_ordering(queryset, self.ordering, default_ordering=('restaurant__name',))


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

    def apply(self, queryset: QuerySet[Hall]) -> QuerySet[Hall]:
        if self.search:
            queryset = queryset.filter(
                Q(name__icontains=self.search)
                | Q(description__icontains=self.search)
            )
        if self.is_active is not None:
            queryset = queryset.filter(is_active=self.is_active)
        return apply_ordering(queryset.distinct(), self.ordering, default_ordering=('name',))


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

    def apply(self, queryset: QuerySet[DiningTable]) -> QuerySet[DiningTable]:
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
    hall_ids: tuple[str, ...] = ()
    is_private: bool | None = None
    is_active: bool | None = None
    ordering: tuple[str, ...] = ()

    @classmethod
    def from_request(cls, request) -> 'ZoneListFilters':
        query_params = request.query_params
        return cls(
            search=get_str_query_param(query_params, 'search'),
            hall_ids=tuple(get_str_list_query_param(query_params, 'hall_id_in')),
            is_private=get_bool_query_param(query_params, 'is_private'),
            is_active=get_bool_query_param(query_params, 'is_active'),
            ordering=get_ordering_query_param(query_params, ZONE_ORDERING_FIELDS),
        )

    def apply(self, queryset: QuerySet[ZoneOrCabin]) -> QuerySet[ZoneOrCabin]:
        if self.search:
            queryset = queryset.filter(Q(name__icontains=self.search) | Q(hall__name__icontains=self.search))
        if self.hall_ids:
            queryset = queryset.filter(hall_id__in=self.hall_ids)
        if self.is_private is not None:
            queryset = queryset.filter(is_private=self.is_private)
        if self.is_active is not None:
            queryset = queryset.filter(is_active=self.is_active)
        return apply_ordering(queryset.distinct(), self.ordering, default_ordering=('hall__name', 'sort_order', 'name'))


@dataclass(frozen=True)
class PrepStationListFilters:
    search: str = ''
    kinds: tuple[str, ...] = ()
    is_active: bool | None = None
    ordering: tuple[str, ...] = ()

    @classmethod
    def from_request(cls, request) -> 'PrepStationListFilters':
        query_params = request.query_params
        return cls(
            search=get_str_query_param(query_params, 'search'),
            kinds=tuple(get_str_list_query_param(query_params, 'kind_in')),
            is_active=get_bool_query_param(query_params, 'is_active'),
            ordering=get_ordering_query_param(query_params, PREP_STATION_ORDERING_FIELDS),
        )

    def apply(self, queryset: QuerySet[PrepStation]) -> QuerySet[PrepStation]:
        if self.search:
            queryset = queryset.filter(
                Q(name__icontains=self.search)
                | Q(code__icontains=self.search)
            )
        if self.kinds:
            queryset = queryset.filter(kind__in=self.kinds)
        if self.is_active is not None:
            queryset = queryset.filter(is_active=self.is_active)
        return apply_ordering(queryset, self.ordering, default_ordering=('name',))


@dataclass(frozen=True)
class CashDeskListFilters:
    search: str = ''
    is_active: bool | None = None
    ordering: tuple[str, ...] = ()

    @classmethod
    def from_request(cls, request) -> 'CashDeskListFilters':
        query_params = request.query_params
        return cls(
            search=get_str_query_param(query_params, 'search'),
            is_active=get_bool_query_param(query_params, 'is_active'),
            ordering=get_ordering_query_param(query_params, CASH_DESK_ORDERING_FIELDS),
        )

    def apply(self, queryset: QuerySet[CashDesk]) -> QuerySet[CashDesk]:
        if self.search:
            queryset = queryset.filter(
                Q(name__icontains=self.search)
                | Q(location__icontains=self.search)
            )
        if self.is_active is not None:
            queryset = queryset.filter(is_active=self.is_active)
        return apply_ordering(queryset, self.ordering, default_ordering=('name',))


@dataclass(frozen=True)
class DistributionPointListFilters:
    search: str = ''
    kinds: tuple[str, ...] = ()
    is_active: bool | None = None
    ordering: tuple[str, ...] = ()

    @classmethod
    def from_request(cls, request) -> 'DistributionPointListFilters':
        query_params = request.query_params
        return cls(
            search=get_str_query_param(query_params, 'search'),
            kinds=tuple(get_str_list_query_param(query_params, 'kind_in')),
            is_active=get_bool_query_param(query_params, 'is_active'),
            ordering=get_ordering_query_param(query_params, DISTRIBUTION_POINT_ORDERING_FIELDS),
        )

    def apply(self, queryset: QuerySet[DistributionPoint]) -> QuerySet[DistributionPoint]:
        if self.search:
            queryset = queryset.filter(
                Q(name__icontains=self.search)
                | Q(integration_channel__icontains=self.search)
                | Q(assigned_hall__name__icontains=self.search)
            )
        if self.kinds:
            queryset = queryset.filter(kind__in=self.kinds)
        if self.is_active is not None:
            queryset = queryset.filter(is_active=self.is_active)
        return apply_ordering(queryset.distinct(), self.ordering, default_ordering=('name',))


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

    def apply(self, queryset: QuerySet[TableSession]) -> QuerySet[TableSession]:
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


@dataclass(frozen=True)
class DeviceListFilters:
    search: str = ''
    modes: tuple[str, ...] = ()
    is_active: bool | None = None
    ordering: tuple[str, ...] = ()

    @classmethod
    def from_request(cls, request) -> 'DeviceListFilters':
        query_params = request.query_params
        return cls(
            search=get_str_query_param(query_params, 'search'),
            modes=tuple(get_str_list_query_param(query_params, 'mode_in')),
            is_active=get_bool_query_param(query_params, 'is_active'),
            ordering=get_ordering_query_param(query_params, DEVICE_ORDERING_FIELDS),
        )

    def apply(self, queryset: QuerySet[Device]) -> QuerySet[Device]:
        if self.search:
            queryset = queryset.filter(
                Q(name__icontains=self.search)
                | Q(code__icontains=self.search)
                | Q(primary_hall__name__icontains=self.search)
            )
        if self.modes:
            queryset = queryset.filter(mode__in=self.modes)
        if self.is_active is not None:
            queryset = queryset.filter(is_active=self.is_active)
        return apply_ordering(queryset.distinct(), self.ordering, default_ordering=('name',))


@dataclass(frozen=True)
class RestaurantListFilters:
    search: str = ''
    is_active: bool | None = None
    ordering: tuple[str, ...] = ()

    @classmethod
    def from_request(cls, request) -> 'RestaurantListFilters':
        query_params = request.query_params
        return cls(
            search=get_str_query_param(query_params, 'search'),
            is_active=get_bool_query_param(query_params, 'is_active'),
            ordering=get_ordering_query_param(query_params, RESTAURANT_ORDERING_FIELDS),
        )

    def apply(self, queryset: QuerySet[Restaurant]) -> QuerySet[Restaurant]:
        if self.search:
            queryset = queryset.filter(
                Q(name__icontains=self.search)
                | Q(slug__icontains=self.search)
                | Q(legal_name__icontains=self.search)
                | Q(phone__icontains=self.search)
            )
        if self.is_active is not None:
            queryset = queryset.filter(is_active=self.is_active)
        return apply_ordering(queryset, self.ordering, default_ordering=('name',))


class AdminSuperuserRequiredMixin:
    permission_classes = [IsAdmin]
