from datetime import timedelta
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from apps.catalog.models import CatalogCategory, CatalogItem
from apps.catalog.serializers import CatalogCategorySerializer, CatalogItemSerializer
from apps.catalog.services.name_translation import uzbek_latin_to_cyrillic
from apps.local_agents.invalidation import broadcast_configuration_invalidation
from common.sale_units import SALE_UNITS
from .access import require_access
from .ai import extract_menu
from .models import CatalogDraft


class ReviewRow(serializers.Serializer):
    selected = serializers.BooleanField(default=True)
    name = serializers.CharField(max_length=255)
    name_ru = serializers.CharField(max_length=255, allow_blank=True, default='')
    category_id = serializers.UUIDField(allow_null=True, default=None)
    category_name = serializers.CharField(max_length=255, allow_blank=True, default='')
    category_mxik = serializers.RegexField(r'^\d{17}$', allow_blank=True, default='')
    price = serializers.IntegerField(min_value=0, max_value=2147483647, allow_null=True)
    sale_unit = serializers.ChoiceField(choices=list(SALE_UNITS))
    description = serializers.CharField(max_length=2000, allow_blank=True, default='')
    evidence = serializers.CharField(max_length=1000, allow_blank=True, default='')
    warning = serializers.CharField(max_length=1000, allow_blank=True, default='')


def create_draft(user, restaurant_id, content, category_id=None):
    restaurant = require_access(user, restaurant_id)
    categories = list(CatalogCategory.objects.filter(restaurant=restaurant, is_active=True))
    default = next((cat for cat in categories if str(cat.pk) == str(category_id)), None)
    if category_id and default is None:
        raise ValidationError('Kategoriya bu shahobchaga tegishli emas.')
    rows = extract_menu(content, [cat.name for cat in categories])
    existing = set(CatalogItem.objects.filter(restaurant=restaurant, archived_at__isnull=True).values_list('name', flat=True))
    existing = {name.casefold() for name in existing}
    for row in rows:
        cat = default or next((cat for cat in categories if cat.name.casefold() == row['category_name'].casefold()), None)
        row.update(selected=True, category_id=str(cat.pk) if cat else None, category_mxik='')
        if cat:
            row['category_name'] = cat.name
        if row['name'].casefold() in existing:
            row['warning'] = 'Shu nomli mahsulot mavjud. Saqlash yangi mahsulot yaratadi. ' + row['warning']
    return CatalogDraft.objects.create(owner=user, restaurant=restaurant, rows=rows,
                                       expires_at=timezone.now() + timedelta(days=1))


def serialize_draft(draft):
    return {'id': str(draft.pk), 'restaurant_id': str(draft.restaurant_id), 'rows': draft.rows,
            'warnings': draft.warnings, 'revision': draft.revision, 'result': draft.result,
            'committed': draft.committed_at is not None, 'expires_at': draft.expires_at.isoformat()}


@transaction.atomic
def commit_draft(user, draft_id, rows, revision):
    draft = get_object_or_404(CatalogDraft.objects.select_for_update(), pk=draft_id, owner=user)
    restaurant = require_access(user, draft.restaurant_id)
    if draft.committed_at:
        return draft  # A lost response/retry must not create duplicate products.
    if draft.expires_at <= timezone.now() or revision != draft.revision:
        raise ValidationError('Draft eskirgan. Uni qayta oching yoki yangi draft tayyorlang.')
    if not isinstance(rows, list) or not 1 <= len(rows) <= 100:
        raise ValidationError('1–100 ta qator yuboring.')
    selected_rows = [row for row in rows if isinstance(row, dict) and row.get('selected', True)]
    if not selected_rows:
        raise ValidationError('Kamida bitta mahsulotni belgilang.')
    validator = ReviewRow(data=selected_rows, many=True)
    validator.is_valid(raise_exception=True)
    created = []
    for index, row in enumerate(validator.validated_data):
        if row['price'] is None:
            raise ValidationError({'rows': {index: 'Narxni kiriting.'}})
        if row['category_id']:
            category = get_object_or_404(CatalogCategory, pk=row['category_id'], restaurant=restaurant, is_active=True)
        else:
            if not row['category_name'] or not row['category_mxik']:
                raise ValidationError({'rows': {index: 'Kategoriyani tanlang yoki yangi kategoriya nomi va MXIK kodini kiriting.'}})
            category = CatalogCategory.objects.filter(restaurant=restaurant, name=row['category_name']).first()
            if category is not None and not category.is_active:
                raise ValidationError('Shu nomli kategoriya yashirilgan. Avval uni faollashtiring yoki boshqa nom kiriting.')
            if category is None:
                require_access(user, restaurant.pk, 'catalog_categories', 'create')
                cat = CatalogCategorySerializer(data={'name': row['category_name'], 'name_uz': row['category_name'],
                                                      'mxik_code': row['category_mxik'], 'is_active': True})
                cat.is_valid(raise_exception=True)
                category = cat.save(restaurant=restaurant)
        # IDs and fields come from validated review input. Existing catalog
        # validation remains authoritative; AI has no write credentials/tools.
        serializer = CatalogItemSerializer(data={
            'name': row['name'], 'name_uz': row['name'], 'name_uz_crl': uzbek_latin_to_cyrillic(row['name']),
            'name_ru': row['name_ru'], 'price': row['price'], 'sale_unit': row['sale_unit'],
            'description': row['description'], 'category': str(category.pk), 'is_active': True,
        })
        serializer.is_valid(raise_exception=True)
        item = serializer.save(restaurant=restaurant)
        created.append({'id': str(item.pk), 'name': item.name})
    draft.rows = rows
    draft.result = {'created': created, 'count': len(created)}
    draft.committed_at = timezone.now()
    draft.revision += 1
    draft.save(update_fields=['rows', 'result', 'committed_at', 'revision', 'updated_at'])
    transaction.on_commit(lambda: broadcast_configuration_invalidation(restaurant_id=restaurant.pk))
    return draft
