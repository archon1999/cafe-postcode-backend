from common.api.scopes import get_optional_request_restaurant


def filter_queryset_by_optional_scope(queryset, request, restaurant_lookup: str = 'restaurant'):
    restaurant = get_optional_request_restaurant(request)
    if restaurant is not None:
        return queryset.filter(**{restaurant_lookup: restaurant})
    if getattr(request.user, 'is_superuser', False):
        return queryset
    return queryset.none()


def filter_queryset_by_optional_restaurant(queryset, request, lookup: str = 'restaurant'):
    restaurant = get_optional_request_restaurant(request)
    if restaurant is None and getattr(request.user, 'is_superuser', False):
        return queryset
    if restaurant is None:
        return queryset.none()
    return queryset.filter(**{lookup: restaurant})
