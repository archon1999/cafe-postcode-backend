from django.db.models import Prefetch, QuerySet

from apps.floor.models import DiningTable, Hall
from .scopes import filter_queryset_by_optional_restaurant


def hall_constructor_queryset(request) -> QuerySet[Hall]:
    table_queryset = DiningTable.objects.order_by('table_number', 'name')
    queryset = Hall.objects.select_related('zone_or_cabin').prefetch_related(Prefetch('tables', queryset=table_queryset))
    return filter_queryset_by_optional_restaurant(queryset, request, lookup='zone_or_cabin__restaurant')
