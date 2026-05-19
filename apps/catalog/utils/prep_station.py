from apps.restaurants.models import PrepStation


def resolve_order_item_prep_station(*, catalog_item, restaurant=None):
    restaurant = restaurant or getattr(catalog_item, 'restaurant', None)

    category = getattr(catalog_item, 'category', None)
    if getattr(category, 'prep_station_id', None):
        return category.prep_station

    if getattr(catalog_item, 'prep_station_id', None):
        return catalog_item.prep_station

    if restaurant is None:
        return None

    station_ids = list(
        PrepStation.objects.filter(restaurant=restaurant, is_active=True).order_by('name').values_list('id', flat=True)[:2]
    )
    if len(station_ids) != 1:
        return None

    return PrepStation.objects.get(pk=station_ids[0])
