from django.db.models import QuerySet

from apps.integrations.models import IntegrationConfig
from .scopes import filter_queryset_by_optional_restaurant


def integration_config_queryset(request, *, include_ordering: bool = False) -> QuerySet[IntegrationConfig]:
    queryset = IntegrationConfig.objects.all()
    if include_ordering:
        queryset = queryset.order_by('kind', 'provider')
    return filter_queryset_by_optional_restaurant(queryset, request)
