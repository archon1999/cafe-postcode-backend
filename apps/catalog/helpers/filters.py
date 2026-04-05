from dataclasses import dataclass

from django.db.models import Q, QuerySet

from apps.catalog.models import CatalogCategory, CatalogItem
from common.api.query_params import (
    apply_ordering,
    get_bool_query_param,
    get_ordering_query_param,
    get_str_list_query_param,
    get_str_query_param,
)
from common.api.scopes import get_optional_request_restaurant

CATEGORY_ORDERING_FIELDS = {
    'name': 'name',
    'mxikCode': 'mxik_code',
    'mxikName': 'mxik_name',
    'sortOrder': 'sort_order',
    'isActive': 'is_active',
}
ITEM_ORDERING_FIELDS = {
    'name': 'name',
    'mxikCode': 'mxik_code',
    'mxikName': 'mxik_name',
    'categoryName': ('category__name', 'name'),
    'prepStationName': ('prep_station__name', 'name'),
    'price': 'price',
    'isActive': 'is_active',
    'isStoplisted': 'is_stoplisted',
}


def filter_catalog_queryset_by_scope(queryset, request, restaurant_lookup: str = 'restaurant'):
    restaurant = get_optional_request_restaurant(request)
    if restaurant is None:
        return queryset
    return queryset.filter(**{restaurant_lookup: restaurant})


@dataclass(frozen=True)
class CategoryListFilters:
    search: str = ''
    is_active: bool | None = None
    ordering: tuple[str, ...] = ()

    @classmethod
    def from_request(cls, request) -> 'CategoryListFilters':
        query_params = request.query_params
        return cls(
            search=get_str_query_param(query_params, 'search'),
            is_active=get_bool_query_param(query_params, 'is_active'),
            ordering=get_ordering_query_param(query_params, CATEGORY_ORDERING_FIELDS),
        )

    def apply(self, queryset: QuerySet[CatalogCategory]) -> QuerySet[CatalogCategory]:
        if self.search:
            queryset = queryset.filter(
                Q(name__icontains=self.search)
                | Q(mxik_code__icontains=self.search)
                | Q(mxik_name__icontains=self.search)
            )
        if self.is_active is not None:
            queryset = queryset.filter(is_active=self.is_active)
        return apply_ordering(queryset, self.ordering, default_ordering=('sort_order', 'name'))


@dataclass(frozen=True)
class ItemListFilters:
    search: str = ''
    category_ids: tuple[str, ...] = ()
    is_active: bool | None = None
    is_stoplisted: bool | None = None
    ordering: tuple[str, ...] = ()

    @classmethod
    def from_request(cls, request) -> 'ItemListFilters':
        query_params = request.query_params
        return cls(
            search=get_str_query_param(query_params, 'search'),
            category_ids=tuple(get_str_list_query_param(query_params, 'category_id_in')),
            is_active=get_bool_query_param(query_params, 'is_active'),
            is_stoplisted=get_bool_query_param(query_params, 'is_stoplisted'),
            ordering=get_ordering_query_param(query_params, ITEM_ORDERING_FIELDS),
        )

    def apply(self, queryset: QuerySet[CatalogItem]) -> QuerySet[CatalogItem]:
        if self.search:
            queryset = queryset.filter(
                Q(name__icontains=self.search)
                | Q(mxik_code__icontains=self.search)
                | Q(mxik_name__icontains=self.search)
                | Q(category__name__icontains=self.search)
                | Q(prep_station__name__icontains=self.search)
            )
        if self.category_ids:
            queryset = queryset.filter(category_id__in=self.category_ids)
        if self.is_active is not None:
            queryset = queryset.filter(is_active=self.is_active)
        if self.is_stoplisted is not None:
            queryset = queryset.filter(is_stoplisted=self.is_stoplisted)
        return apply_ordering(queryset.distinct(), self.ordering, default_ordering=('name',))
