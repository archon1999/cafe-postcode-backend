from common.api.scopes import get_optional_request_restaurant


def filter_queryset_by_optional_scope(queryset, request, restaurant_lookup: str = 'restaurant'):
    restaurant = get_optional_request_restaurant(request)
    if restaurant is not None:
        return queryset.filter(**{restaurant_lookup: restaurant})

    return queryset


def filter_queryset_by_optional_restaurant(queryset, request, lookup: str = 'restaurant'):
    restaurant = get_optional_request_restaurant(request)
    if restaurant is None:
        return queryset
    return queryset.filter(**{lookup: restaurant})
