"""Allowlisted mutations; scope and permissions are rechecked at confirmation."""
from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import ValidationError
from apps.catalog.models import CatalogCategory, CatalogItem
from apps.catalog.serializers import CatalogCategorySerializer, CatalogItemSerializer
from apps.floor.models import DiningTable, Hall, ZoneOrCabin, TableSession, TableSessionTable
from apps.restaurants.models import PrepStation
from apps.floor.api.admin.serializers import DiningTableSerializer, HallSerializer, ZoneOrCabinSerializer
from apps.floor.services import ACTIVE_SESSION_STATUSES
from apps.local_agents.invalidation import broadcast_configuration_invalidation
from .access import require_access

RESOURCES = {
    'category': (CatalogCategory, CatalogCategorySerializer, 'catalog_categories', 'restaurant'),
    'item': (CatalogItem, CatalogItemSerializer, 'catalog_items', 'restaurant'),
    'zone': (ZoneOrCabin, ZoneOrCabinSerializer, 'zones', 'restaurant'),
    'hall': (Hall, HallSerializer, 'halls', 'zone_or_cabin__restaurant'),
    'table': (DiningTable, DiningTableSerializer, 'tables', 'hall__zone_or_cabin__restaurant'),
}
FIELDS = {
    'category': {'name', 'name_uz', 'mxik_code', 'is_active', 'prep_station'},
    'item': {'name', 'name_uz', 'price', 'is_active', 'is_stoplisted', 'category', 'sale_unit'},
    'zone': {'name', 'is_active'},
    'hall': {'name', 'is_active', 'zone_or_cabin_id'},
    'table': {'name', 'seat_count', 'hall', 'is_active'},
}


def scoped_objects(user, restaurant_id, kind, action='view'):
    if kind not in RESOURCES:
        raise ValidationError('Amal topilmadi.')
    model, _, resource, lookup = RESOURCES[kind]
    restaurant = require_access(user, restaurant_id, resource, action)
    queryset = model.objects.filter(**{lookup: restaurant})
    if kind == 'item':
        queryset = queryset.filter(archived_at__isnull=True)
    return queryset


@transaction.atomic
def apply_action(account, pending):
    kind = pending['kind']
    pk = pending.get('pk')
    data = dict(pending['data'])
    if kind not in FIELDS or not data or set(data) - FIELDS[kind]:
        raise ValidationError('Bu maydonni bot orqali o‘zgartirib bo‘lmaydi.')
    objects = scoped_objects(account.user, account.restaurant_id, kind, 'update' if pk else 'create')
    instance = get_object_or_404(objects.select_for_update(), pk=pk) if pk else None
    # Related IDs are never accepted based on the serializer's global queryset.
    for field, related_kind in [('category', 'category'), ('zone_or_cabin_id', 'zone'), ('hall', 'hall')]:
        if field in data:
            get_object_or_404(scoped_objects(account.user, account.restaurant_id, related_kind), pk=data[field], is_active=True)
    if 'prep_station' in data:
        get_object_or_404(PrepStation, pk=data['prep_station'], restaurant_id=account.restaurant_id, is_active=True)
    if data.get('is_active') is False and kind in ('hall', 'table', 'zone'):
        lookup = {'hall': 'table__hall_id', 'table': 'table_id', 'zone': 'table__hall__zone_or_cabin_id'}[kind]
        if TableSession.objects.filter(**{lookup: pk}, status__in=ACTIVE_SESSION_STATUSES).exists():
            raise ValidationError('Ochiq stol sessiyalari bor. Avval ularni yakunlang.')
        if TableSessionTable.objects.filter(**{lookup: pk}, released_at__isnull=True,
                                            session__status__in=ACTIVE_SESSION_STATUSES).exists():
            raise ValidationError('Bu joy boshqa stol sessiyasiga biriktirilgan. Avval uni yakunlang.')
        if kind == 'zone' and Hall.objects.filter(zone_or_cabin_id=pk, is_active=True).exists():
            raise ValidationError('Hududni yashirishdan oldin undagi zallarni yashiring.')
    if kind == 'table' and not pk:
        data['table_number'] = data['name']
    if kind == 'table' and 'seat_count' in data:
        if data['seat_count'] not in DiningTable.get_supported_seat_counts():
            raise ValidationError('O‘rindiq soni 2–100 oralig‘ida bo‘lishi kerak.')
        data['shape_variant'] = DiningTable.get_default_shape_variant(data['seat_count'])
    serializer = RESOURCES[kind][1](instance, data=data, partial=bool(pk))
    serializer.is_valid(raise_exception=True)
    kwargs = {'restaurant': account.restaurant} if not pk and kind in ('category', 'item', 'zone') else {}
    obj = serializer.save(**kwargs)
    transaction.on_commit(lambda: broadcast_configuration_invalidation(restaurant_id=account.restaurant_id))
    return obj
