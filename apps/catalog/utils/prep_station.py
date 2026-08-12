from apps.restaurants.models import PrepStation


_DEFAULT_PREP_STATION_UNSET = object()


def resolve_single_active_prep_station(*, restaurant):
    """Return the restaurant fallback only when exactly one station is active."""
    stations = list(
        PrepStation.objects.filter(restaurant=restaurant, is_active=True).order_by('name')[:2]
    )
    return stations[0] if len(stations) == 1 else None


def resolve_order_item_prep_station(
    *,
    catalog_item,
    restaurant=None,
    default_prep_station=_DEFAULT_PREP_STATION_UNSET,
):
    restaurant = restaurant or getattr(catalog_item, 'restaurant', None)

    category = getattr(catalog_item, 'category', None)
    if getattr(category, 'prep_station_id', None):
        return category.prep_station

    if getattr(catalog_item, 'prep_station_id', None):
        return catalog_item.prep_station

    if restaurant is None:
        return None

    if default_prep_station is not _DEFAULT_PREP_STATION_UNSET:
        return default_prep_station

    station_ids = list(
        PrepStation.objects.filter(restaurant=restaurant, is_active=True).order_by('name').values_list('id', flat=True)[:2]
    )
    if len(station_ids) != 1:
        return None

    return PrepStation.objects.get(pk=station_ids[0])
