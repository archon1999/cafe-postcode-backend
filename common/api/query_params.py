from collections.abc import Iterable, Mapping, Sequence

from django.db.models import QuerySet

DEFAULT_TRUTHY_QUERY_VALUES = frozenset({'1', 'true', 'yes'})
DEFAULT_FALSY_QUERY_VALUES = frozenset({'0', 'false', 'no'})


def get_query_param(
    query_params: Mapping[str, str | None],
    key: str,
    *,
    aliases: Iterable[str] = (),
) -> str | None:
    for candidate in (key, *aliases):
        raw_value = query_params.get(candidate)
        if raw_value is not None:
            return raw_value

    return None


def get_str_query_param(
    query_params: Mapping[str, str | None],
    key: str,
    *,
    aliases: Iterable[str] = (),
    default: str = '',
) -> str:
    raw_value = get_query_param(query_params, key, aliases=aliases)
    if raw_value is None:
        return default

    return raw_value.strip()


def get_str_list_query_param(
    query_params: Mapping[str, str | None],
    key: str,
    *,
    aliases: Iterable[str] = (),
    separator: str = ',',
    allowed_values: Iterable[str] | None = None,
) -> list[str]:
    raw_value = get_query_param(query_params, key, aliases=aliases)
    if not raw_value:
        return []

    values = [item.strip() for item in raw_value.split(separator) if item.strip()]
    if allowed_values is None:
        return values

    allowed_values_set = set(allowed_values)
    return [value for value in values if value in allowed_values_set]


def get_bool_query_param(
    query_params: Mapping[str, str | None],
    key: str,
    *,
    aliases: Iterable[str] = (),
    truthy_values: Iterable[str] = DEFAULT_TRUTHY_QUERY_VALUES,
    falsy_values: Iterable[str] = DEFAULT_FALSY_QUERY_VALUES,
) -> bool | None:
    raw_value = get_query_param(query_params, key, aliases=aliases)
    if raw_value is None:
        return None

    normalized = raw_value.strip().lower()
    if normalized in truthy_values:
        return True
    if normalized in falsy_values:
        return False
    return None


def get_ordering_query_param(
    query_params: Mapping[str, str | None],
    ordering_map: Mapping[str, str | Sequence[str]],
    *,
    key: str = 'ordering',
    aliases: Iterable[str] = (),
) -> tuple[str, ...]:
    raw_value = get_query_param(query_params, key, aliases=aliases)
    if not raw_value:
        return ()

    resolved_fields: list[str] = []
    for item in raw_value.split(','):
        normalized = item.strip()
        if not normalized:
            continue

        is_desc = normalized.startswith('-')
        requested_field = normalized[1:] if is_desc else normalized
        mapped_field = ordering_map.get(requested_field)
        if mapped_field is None:
            continue

        mapped_fields = (mapped_field,) if isinstance(mapped_field, str) else tuple(mapped_field)
        for field in mapped_fields:
            resolved_fields.append(f'-{field}' if is_desc else field)

    return tuple(resolved_fields)


def apply_ordering(
    queryset: QuerySet,
    ordering: Sequence[str],
    *,
    default_ordering: Sequence[str] = (),
) -> QuerySet:
    if ordering:
        return queryset.order_by(*ordering)
    if default_ordering:
        return queryset.order_by(*default_ordering)
    return queryset
