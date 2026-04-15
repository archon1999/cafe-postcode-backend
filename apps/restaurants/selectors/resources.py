from dataclasses import dataclass

from django.db.models import Q, QuerySet

from apps.restaurants.helpers import (
    get_cash_desk_model,
    get_distribution_point_model,
    get_prep_station_model,
)
from common.api.query_params import (
    apply_ordering,
    get_bool_query_param,
    get_ordering_query_param,
    get_str_list_query_param,
    get_str_query_param,
)

CashDesk = get_cash_desk_model()
DistributionPoint = get_distribution_point_model()
PrepStation = get_prep_station_model()

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

    def apply(self, queryset: QuerySet) -> QuerySet:
        if self.search:
            queryset = queryset.filter(Q(name__icontains=self.search) | Q(code__icontains=self.search))
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

    def apply(self, queryset: QuerySet) -> QuerySet:
        if self.search:
            queryset = queryset.filter(Q(name__icontains=self.search) | Q(location__icontains=self.search))
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

    def apply(self, queryset: QuerySet) -> QuerySet:
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
