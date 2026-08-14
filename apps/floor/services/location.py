from django.db.models import Exists, OuterRef, QuerySet

from apps.floor.models import ZoneOrCabin


ZONE_VISIBILITY_ANNOTATION = "has_multiple_active_zones"


def annotate_zone_name_visibility(
    queryset: QuerySet, *, restaurant_id_field: str = "restaurant_id"
) -> QuerySet:
    """Annotate zone visibility without adding a serializer-time query."""
    second_active_zone = ZoneOrCabin.objects.filter(
        restaurant_id=OuterRef(restaurant_id_field),
        is_active=True,
    ).order_by("pk")[1:2]
    return queryset.annotate(
        **{ZONE_VISIBILITY_ANNOTATION: Exists(second_active_zone)}
    )


def restaurant_has_multiple_active_zones(restaurant_id) -> bool:
    """Return whether a restaurant needs zone context to identify a table."""
    if not restaurant_id:
        return False
    return ZoneOrCabin.objects.filter(
        restaurant_id=restaurant_id,
        is_active=True,
    )[1:2].exists()


def table_session_zone_name(session) -> str:
    hall = getattr(session, "hall", None) if session is not None else None
    zone = getattr(hall, "zone_or_cabin", None) if hall is not None else None
    return str(getattr(zone, "name", "") or "")
