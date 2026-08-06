from dataclasses import dataclass
from uuid import UUID

from django.db.models import Q, QuerySet
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError

from apps.restaurants.models import Restaurant


DASHBOARD_RESTAURANT_HEADER = 'X-Dashboard-Restaurant-Id'
DASHBOARD_ALL_RESTAURANTS_VALUE = 'all'


@dataclass(frozen=True)
class DashboardRestaurantScope:
    selected_restaurant: Restaurant
    restaurants: tuple[Restaurant, ...]
    is_all: bool = False

    @property
    def query_scope(self):
        return self.restaurants if self.is_all else self.selected_restaurant


def get_dashboard_accessible_restaurants(user) -> QuerySet:
    queryset = Restaurant.objects.select_related(
        'parent_restaurant',
        'entitlement',
        'entitlement__tariff',
    ).prefetch_related(
        'entitlement__permissions',
        'entitlement__tariff__permissions',
    ).filter(
        is_active=True,
        entitlement__is_active=True,
    ).filter(
        Q(entitlement__permissions__code='dashboard.view')
        | Q(entitlement__tariff__permissions__code='dashboard.view')
    ).distinct().order_by('name')

    if user.is_superuser:
        return queryset

    restaurant = user.get_restaurant_scope()
    if restaurant is None:
        return queryset.none()
    if restaurant.parent_restaurant_id is not None:
        return queryset.filter(pk=restaurant.pk)
    return queryset.filter(
        Q(pk=restaurant.pk) | Q(parent_restaurant_id=restaurant.pk),
    )


def get_dashboard_restaurant_scope(request) -> DashboardRestaurantScope:
    restaurants = tuple(get_dashboard_accessible_restaurants(request.user))
    if not restaurants:
        raise NotFound('Restaurant is not available for the current user.')

    requested_value = str(
        request.headers.get(DASHBOARD_RESTAURANT_HEADER) or ''
    ).strip()
    primary = request.user.get_restaurant_scope()
    default_restaurant = next(
        (restaurant for restaurant in restaurants if primary and restaurant.pk == primary.pk),
        restaurants[0],
    )

    if not requested_value:
        return DashboardRestaurantScope(
            selected_restaurant=default_restaurant,
            restaurants=(default_restaurant,),
        )

    if requested_value == DASHBOARD_ALL_RESTAURANTS_VALUE:
        if len(restaurants) < 2:
            return DashboardRestaurantScope(
                selected_restaurant=default_restaurant,
                restaurants=(default_restaurant,),
            )
        return DashboardRestaurantScope(
            selected_restaurant=default_restaurant,
            restaurants=restaurants,
            is_all=True,
        )

    try:
        requested_id = UUID(requested_value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(
            {'restaurantId': 'Selected restaurant id is invalid.'}
        ) from exc

    selected = next(
        (restaurant for restaurant in restaurants if restaurant.pk == requested_id),
        None,
    )
    if selected is None:
        raise PermissionDenied('You cannot access the selected restaurant dashboard.')
    return DashboardRestaurantScope(
        selected_restaurant=selected,
        restaurants=(selected,),
    )


__all__ = [
    'DASHBOARD_ALL_RESTAURANTS_VALUE',
    'DASHBOARD_RESTAURANT_HEADER',
    'DashboardRestaurantScope',
    'get_dashboard_accessible_restaurants',
    'get_dashboard_restaurant_scope',
]
