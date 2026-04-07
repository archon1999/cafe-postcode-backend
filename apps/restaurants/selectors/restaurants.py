from dataclasses import dataclass

from django.db.models import Q, QuerySet

from apps.restaurants.helpers import get_restaurant_model
from common.api.query_params import (
    apply_ordering,
    get_bool_query_param,
    get_ordering_query_param,
    get_str_query_param,
)

Restaurant = get_restaurant_model()

RESTAURANT_ORDERING_FIELDS = {
    'name': 'name',
    'slug': 'slug',
    'legalName': 'legal_name',
    'phone': 'phone',
    'currency': 'currency',
    'isActive': 'is_active',
    'activatedAt': 'activated_at',
    'deactivatedAt': 'deactivated_at',
    'startsOn': 'entitlement__starts_on',
    'expiresOn': 'entitlement__expires_on',
    'billingPeriod': 'entitlement__billing_period',
}


def get_restaurants_queryset_for_request(request):
    queryset = Restaurant.objects.select_related(
        'business_partner',
        'entitlement',
        'entitlement__tariff',
    ).prefetch_related(
        'entitlement__permissions',
        'entitlement__allowed_roles',
        'entitlement__tariff__permissions',
        'entitlement__tariff__allowed_roles',
    ).order_by('name')
    if request.user.is_superuser or request.user.role_code == 'product_owner':
        return queryset

    business_partner = request.user.get_business_partner_scope()
    if business_partner is not None:
        return queryset.filter(business_partner_id=business_partner.id)

    restaurant = request.user.get_restaurant_scope()
    if restaurant is not None:
        return queryset.filter(pk=restaurant.id)

    return queryset.none()


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

    def apply(self, queryset: QuerySet) -> QuerySet:
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
