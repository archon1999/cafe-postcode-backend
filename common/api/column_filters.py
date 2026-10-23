"""Allowlisted admin table filters, applied after permission/restaurant scoping.

This is an admin read contract; POS and Local Agent queries are unaffected.
The public field names deliberately never accept arbitrary ORM lookups.
"""
import json
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from rest_framework.exceptions import ValidationError
from rest_framework.filters import BaseFilterBackend


FILTER_SCHEMAS = json.loads(Path(__file__).with_name('column_filter_fields.json').read_text())
MODEL_SCHEMAS = {entry['model']: entry['fields'] for entry in FILTER_SCHEMAS.values()}
OPERATORS = {
    'text': {'contains', 'equals', 'not_equal', 'starts_with'},
    'number': {'equals', 'not_equal', 'gt', 'gte', 'lt', 'lte', 'between'},
    'date': {'equals', 'gte', 'lte', 'between'},
    'option': {'equals', 'not_equal', 'in'},
    'boolean': {'equals'},
}


def invalid():
    raise ValidationError({'columnFilters': 'Invalid column filter. Check its field, operator and values.'})


def parse_value(value, definition):
    if not isinstance(value, str) or not value.strip() or len(value) > 250:
        invalid()
    value = value.strip()
    kind = definition['kind']
    if kind == 'number':
        try:
            number = Decimal(value)
        except InvalidOperation:
            invalid()
        if not number.is_finite() or abs(number) > Decimal('1e18') or number.as_tuple().exponent < -12:
            invalid()
        return number
    if kind == 'date':
        try:
            return date.fromisoformat(value)
        except ValueError:
            invalid()
    if kind == 'boolean':
        if value not in ('true', 'false'):
            invalid()
        return value == 'true'
    if kind == 'option' and value not in definition.get('options', []):
        invalid()
    return value


def apply_column_filters(queryset, raw):
    if raw in (None, ''):
        return queryset
    if not isinstance(raw, str) or len(raw) > 16000:
        invalid()
    try:
        filters = json.loads(raw)
    except (ValueError, TypeError):
        invalid()
    if not isinstance(filters, list) or len(filters) > 20:
        invalid()
    fields = MODEL_SCHEMAS.get(queryset.model._meta.label_lower, {})
    seen = set()
    for item in filters:
        if not isinstance(item, dict) or set(item) != {'field', 'operator', 'values'}:
            invalid()
        field, operator, values = item['field'], item['operator'], item['values']
        if not isinstance(field, str) or field not in fields or field in seen:
            invalid()
        seen.add(field)
        definition = fields[field]
        kind = definition['kind']
        if not isinstance(operator, str) or operator not in OPERATORS[kind] or not isinstance(values, list):
            invalid()
        count = 2 if operator == 'between' else 1
        if (operator == 'in' and not 1 <= len(values) <= 30) or (operator != 'in' and len(values) != count):
            invalid()
        parsed = [parse_value(value, definition) for value in values]
        if operator == 'between' and parsed[0] > parsed[1]:
            invalid()
        lookup = definition['lookup'] + ('__date' if kind == 'date' else '')
        suffix = {'contains': 'icontains', 'starts_with': 'istartswith', 'between': 'range'}.get(operator, operator)
        if operator in ('equals', 'not_equal'):
            suffix = 'iexact' if kind == 'text' else 'exact'
        value = parsed if operator in ('between', 'in') else parsed[0]
        predicate = {f'{lookup}__{suffix}': value}
        queryset = queryset.exclude(**predicate) if operator == 'not_equal' else queryset.filter(**predicate)
    return queryset


class AdminColumnFilterBackend(BaseFilterBackend):
    def filter_queryset(self, request, queryset, view):
        raw = request.query_params.get('column_filters', request.query_params.get('columnFilters'))
        if raw is None:
            return queryset
        if request.method != 'GET' or not request.path.startswith('/api/v1/admin/') or getattr(view, 'kwargs', {}).get('pk'):
            invalid()
        return apply_column_filters(queryset, raw)
