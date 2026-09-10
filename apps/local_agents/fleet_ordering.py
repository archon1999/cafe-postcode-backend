from django.db.models import Case, F, IntegerField, Value, When
from django.db.models.functions import Lower, TruncMinute

from apps.local_agents.releases import VERSION_PATTERN


def version_sort_key(version):
    match = VERSION_PATTERN.fullmatch(str(version or '').strip())
    if match is None:
        return (0, 0, 0, 0, False, '')
    return (1, *(int(match.group(index)) for index in range(1, 4)), not bool(match.group(4)), match.group(4) or '')


def order_fleet_by_recent_minute(queryset):
    # Rank only distinct versions, then let the database sort the entire fleet
    # before pagination. Numeric versions must put 2.10.0 ahead of 2.9.0.
    versions = list(queryset.order_by().values_list('version', flat=True).distinct())
    keys = sorted({version_sort_key(version) for version in versions})
    ranks = {key: rank for rank, key in enumerate(keys)}
    version_rank = Case(
        *(When(version=version, then=Value(ranks[version_sort_key(version)])) for version in versions),
        default=Value(0),
        output_field=IntegerField(),
    )
    return queryset.alias(
        last_seen_minute=TruncMinute('last_seen_at'),
        fleet_version_rank=version_rank,
    ).order_by(
        F('last_seen_minute').desc(nulls_last=True),
        '-fleet_version_rank',
        Lower('restaurant__name'),
        'restaurant__name',
        'pk',
    )
