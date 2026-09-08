"""Transactional stock ledger. POS and HTTP callers share the same invariants.

Warehouse rows serialize ledger writes (including previously nonexistent balances).
Balances are projections; posted documents/movements are never rewritten. A count
uses the ledger revision captured when its draft is created, not a moving target.
"""
from common.sale_units import sale_quantity_step

from collections import defaultdict
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import hashlib
import json
import uuid

from django.utils.translation import gettext as _
from django.db import transaction
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Max, Sum
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.exceptions import ValidationError

from apps.catalog.models import CatalogItem, ModifierOption
from apps.restaurants.models import Restaurant
from .models import (ConsumptionResolution, InventoryItem, OrderConsumption, Recipe,
                     RecipeLine, StockBalance, StockDocument, StockDocumentLine,
                     StockMovement, Supplier, Warehouse)

ZERO = Decimal('0')
SIX = Decimal('0.000001')
MANUAL_KINDS = {'opening', 'receipt', 'issue', 'supplier_return', 'customer_return', 'stocktake'}
INBOUND_KINDS = {'opening', 'receipt', 'customer_return', 'sale_return'}
_replay = ContextVar('inventory_replay', default=None)


def decimal(value, label='quantity', *, minimum=None):
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValidationError({label: _('Yaroqli son kiriting.')})
    if not result.is_finite() or abs(result) >= Decimal('1000000000000'):
        raise ValidationError({label: _('Son ruxsat etilgan chegaradan tashqarida.')})
    if minimum is not None and result < minimum:
        raise ValidationError({label: _('Qiymat kamida %(minimum)s bo‘lishi kerak.') % {'minimum': minimum}})
    if result != result.quantize(SIX):
        raise ValidationError({label: _('Ko‘pi bilan 6 ta kasr xonasi mumkin.')})
    return result


def q(value):
    try:
        result = Decimal(value).quantize(SIX, rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError, ValueError):
        raise ValidationError(_('Hisob natijasi ruxsat etilgan son chegarasidan tashqarida.'))
    if not result.is_finite() or abs(result) >= Decimal('1000000000000000000'):
        raise ValidationError(_('Hisob natijasi ruxsat etilgan son chegarasidan tashqarida.'))
    return result


def actor_name(actor):
    return str(getattr(actor, 'full_name', '') or getattr(actor, 'username', ''))[:200]


def scoped(model, restaurant, pk, label, **filters):
    try:
        found = model.objects.filter(restaurant=restaurant, pk=pk, **filters).first()
    except (ValueError, TypeError, DjangoValidationError):
        found = None
    if not found:
        raise ValidationError({label: _('Yozuv shu restoranda topilmadi.')})
    return found


@transaction.atomic
def default_warehouse(restaurant):
    Restaurant.objects.select_for_update().get(pk=restaurant.pk)
    result = Warehouse.objects.filter(restaurant=restaurant, is_default=True, is_active=True).first()
    if result:
        return result
    result = Warehouse.objects.filter(restaurant=restaurant, is_active=True).first()
    if result:
        result.is_default = True
        result.save(update_fields=['is_default', 'updated_at'])
        return result
    return Warehouse.objects.create(restaurant=restaurant, name='Asosiy ombor', is_default=True)


def locked_balance(warehouse, item):
    # Caller holds warehouse lock, so the get_or_create also has one writer.
    return StockBalance.objects.get_or_create(warehouse=warehouse, item=item)[0]


def make_document(restaurant, warehouse, kind, actor=None, **kwargs):
    return StockDocument.objects.create(
        restaurant=restaurant, warehouse=warehouse, kind=kind,
        number=f'OMB-{timezone.localdate():%Y%m%d}-{uuid.uuid4().hex[:12].upper()}',
        created_by=actor, created_by_name=actor_name(actor), **kwargs)


def document_digest(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()


def set_document_lines(document, lines):
    if not isinstance(lines, list) or not lines or len(lines) > 500:
        raise ValidationError({'lines': _('1 dan 500 tagacha mahsulot qatori kiriting.')})
    prepared = []
    seen = set()
    previous_lines = {str(line.item_id): line for line in document.lines.all()}
    for raw in lines:
        item = scoped(InventoryItem, document.restaurant, raw.get('item'), 'item', is_active=True)
        if item.pk in seen:
            raise ValidationError({'lines': _('Bir hujjatda mahsulot takrorlanmasin.')})
        seen.add(item.pk)
        count_recorded = raw.get('quantity') is not None
        if not count_recorded and document.kind != 'stocktake':
            raise ValidationError({'quantity': _('Miqdor majburiy.')})
        quantity = decimal(raw.get('quantity') if count_recorded else 0, minimum=ZERO)
        if quantity == 0 and document.kind != 'stocktake':
            raise ValidationError({'quantity': _('Miqdor noldan katta bo‘lishi kerak.')})
        previous = previous_lines.get(str(item.pk))
        unit = raw.get('input_unit', previous.input_unit if previous else 'base')
        if unit not in {'base', 'purchase'}:
            raise ValidationError({'inputUnit': _('base yoki purchase tanlang.')})
        if document.kind == 'stocktake' and unit != 'base':
            raise ValidationError({'inputUnit': _('Sanash asosiy birlikda kiritiladi.')})
        factor = item.purchase_factor if unit == 'purchase' else Decimal('1')
        base_quantity = q(quantity * factor)
        if base_quantity >= Decimal('100000000000000'):
            raise ValidationError({'quantity': _('Asosiy birlikka o‘girilgan miqdor juda katta.')})
        if item.base_unit == 'piece' and base_quantity != base_quantity.to_integral_value():
            raise ValidationError({'quantity': _('Dona bilan hisoblanadigan mahsulot butun bo‘lishi kerak.')})
        preserved_cost = (previous.unit_cost if previous.input_unit == unit else q(previous.base_unit_cost * factor)) if previous else ZERO
        cost = decimal(raw.get('unit_cost', preserved_cost), 'unitCost', minimum=ZERO)
        balance = locked_balance(document.warehouse, item)
        prepared.append(dict(document=document, item=item, item_name=item.name, base_unit=item.base_unit,
                             quantity=quantity, count_recorded=count_recorded, input_unit=unit, unit_cost=cost,
                             base_quantity=base_quantity, base_unit_cost=q(cost / factor),
                             expected_quantity=balance.quantity, expected_revision=balance.revision,
                             tolerance_percent=item.tolerance_percent, tolerance_quantity=item.tolerance_quantity,
                             tolerance_value=item.tolerance_value,
                             lot_number=raw.get('lot_number', ''), expires_on=raw.get('expires_on')))
    document.lines.all().delete()  # Draft-only caller; posted rows never enter here.
    StockDocumentLine.objects.bulk_create([StockDocumentLine(**values) for values in prepared])


@transaction.atomic
def create_document(restaurant, data, actor=None):
    Restaurant.objects.select_for_update().get(pk=restaurant.pk)
    kind = data.get('kind')
    if kind not in MANUAL_KINDS:
        raise ValidationError({'kind': _('Hujjat turi noto‘g‘ri.')})
    key = str(data.get('idempotency_key') or '')
    if len(key) > 200:
        raise ValidationError({'idempotencyKey': _('Kalit juda uzun.')})
    digest = document_digest(data)
    if key:
        existing = StockDocument.objects.filter(restaurant=restaurant, idempotency_key=key).first()
        if existing:
            if existing.request_digest != digest:
                raise ValidationError({'idempotencyKey': _('Kalit boshqa hujjat uchun ishlatilgan.')})
            return existing
    warehouse = scoped(Warehouse, restaurant, data.get('warehouse'), 'warehouse', is_active=True)
    Warehouse.objects.select_for_update().get(pk=warehouse.pk)
    supplier = scoped(Supplier, restaurant, data['supplier'], 'supplier', is_active=True) if data.get('supplier') else None
    fields = {key: data[key] for key in ('reference', 'reason', 'occurred_at', 'attachment_url', 'responsible_name', 'notes') if key in data}
    document = make_document(restaurant, warehouse, kind, actor, supplier=supplier,
                             idempotency_key=key, request_digest=digest, **fields)
    set_document_lines(document, data.get('lines'))
    return document


@transaction.atomic
def update_document(document, data):
    document = StockDocument.objects.select_for_update().get(pk=document.pk)
    if document.status != 'draft':
        raise ValidationError(_('Tasdiqlangan hujjatni tahrirlash mumkin emas. Teskari hujjat yarating.'))
    Warehouse.objects.select_for_update().get(pk=document.warehouse_id)
    if 'kind' in data and data['kind'] != document.kind or 'warehouse' in data and str(data['warehouse']) != str(document.warehouse_id):
        raise ValidationError(_('Ombor yoki hujjat turini almashtirish uchun yangi hujjat yarating.'))
    if document.kind == 'stocktake' and 'lines' in data:
        # Preserve the original cut-off when entering/correcting counted quantities.
        previous = {str(line.item_id): line for line in document.lines.all()}
        if set(str(row.get('item')) for row in data['lines']) != set(previous):
            raise ValidationError(_('Sanash mahsulotlari o‘zgarsa yangi inventarizatsiya yarating.'))
        set_document_lines(document, data['lines'])
        for line in document.lines.all():
            old = previous[str(line.item_id)]
            line.expected_quantity, line.expected_revision = old.expected_quantity, old.expected_revision
            line.save(update_fields=['expected_quantity', 'expected_revision'])
    elif 'lines' in data:
        set_document_lines(document, data['lines'])
    if 'supplier' in data:
        document.supplier = scoped(Supplier, document.restaurant, data['supplier'], 'supplier') if data['supplier'] else None
    for key in ('reference', 'reason', 'occurred_at', 'attachment_url', 'responsible_name', 'notes'):
        if key in data:
            setattr(document, key, data[key])
    document.save()
    return document


def record_movement(document, line, quantity, cost, *, order_item=None, exact_value=None):
    balance = locked_balance(document.warehouse, line.item)
    quantity, cost = q(quantity), q(cost)
    value = q(quantity * cost) if exact_value is None else q(exact_value)
    old_quantity, old_value = balance.quantity, balance.value
    balance.quantity = q(old_quantity + quantity)
    if abs(balance.quantity) >= Decimal('100000000000000') or abs(quantity) >= Decimal('100000000000000'):
        raise ValidationError(_('Ombor miqdori ruxsat etilgan chegaradan oshadi.'))
    balance.value = q(balance.value + value)
    valuation_adjustment = ZERO
    # Negative stock was provisionally costed. A receipt crossing zero corrects
    # its provisional valuation explicitly on the immutable movement rather
    # than silently allowing the projection to diverge from the ledger.
    if balance.quantity > 0:
        if old_quantity < 0 and quantity > 0 and exact_value is None:
            balance.value = q(balance.quantity * cost)
            valuation_adjustment = q(balance.value - old_value - value)
            value += valuation_adjustment
        balance.average_cost = q(balance.value / balance.quantity)
        if balance.average_cost >= Decimal('100000000000000'):
            raise ValidationError(_('Tannarx ruxsat etilgan chegaradan oshadi.'))
        if balance.average_cost < 0:
            # Reversing old-cost receipts after subsequent issues can imply
            # negative value; reject instead of producing impossible inventory.
            raise ValidationError(_('Teskari yozuv manfiy tannarx hosil qiladi. Tuzatish inventarizatsiyasini kiriting.'))
    elif balance.quantity == 0:
        # Keep ledger/projection values exactly equal; rounding residue only.
        if balance.value:
            valuation_adjustment -= balance.value
            value = q(value - balance.value)
            balance.value = ZERO
    balance.revision += 1
    balance.save()
    return StockMovement.objects.create(document=document, line=line, warehouse=document.warehouse,
                                        item=line.item, quantity=quantity, unit_cost=cost, value=value,
                                        valuation_adjustment=valuation_adjustment,
                                        balance_after=balance.quantity, revision=balance.revision,
                                        occurred_at=document.occurred_at, order_item=order_item)


def finish_document(document, actor=None):
    document.status, document.posted_at = 'posted', timezone.now()
    document.posted_by, document.posted_by_name = actor, actor_name(actor)
    document.total_value = document.movements.aggregate(total=Sum('value'))['total'] or ZERO
    document.save(update_fields=['status', 'posted_at', 'posted_by', 'posted_by_name', 'total_value', 'updated_at'])
    return document


@transaction.atomic
def post_document(document, actor=None, allow_negative=False):
    document = StockDocument.objects.select_for_update().get(pk=document.pk)
    if document.status != 'draft':
        return document
    Warehouse.objects.select_for_update().get(pk=document.warehouse_id)
    if not document.warehouse.is_active:
        raise ValidationError({'warehouse': _('Faol bo‘lmagan ombor uchun yangi hujjat tasdiqlanmaydi.')})
    if document.kind not in MANUAL_KINDS:
        raise ValidationError(_('Bu hujjat faqat tizim orqali yaratiladi.'))
    if not document.reference.strip() or not document.responsible_name.strip():
        raise ValidationError(_('Asl hujjat raqami va mas’ul shaxs majburiy.'))
    if document.kind in {'issue', 'supplier_return', 'customer_return', 'stocktake'} and not document.reason.strip():
        raise ValidationError({'reason': _('Sabab majburiy.')})
    if document.kind in {'receipt', 'supplier_return'} and not document.supplier_id:
        raise ValidationError({'supplier': _('Yetkazib beruvchi majburiy.')})
    if document.occurred_at > timezone.now() + timedelta(minutes=5):
        raise ValidationError({'occurredAt': _('Kelajakdagi hujjatni tasdiqlab bo‘lmaydi.')})
    lines = list(document.lines.select_related('item'))
    if not lines:
        raise ValidationError({'lines': _('Mahsulot qatorlari kerak.')})
    for line in lines:
        balance = locked_balance(document.warehouse, line.item)
        if document.kind == 'stocktake':
            if not line.count_recorded:
                raise ValidationError({'lines': _('%(item)s: haqiqiy miqdor hali kiritilmagan.') % {'item': line.item_name}})
            if balance.revision != line.expected_revision:
                raise ValidationError({'lines': _('%(item)s: sanash davomida harakat bo‘lgan. Yangi inventarizatsiya yarating.') % {'item': line.item_name}})
            quantity = q(line.base_quantity - line.expected_quantity)
            cost = balance.average_cost
            since = balance.last_counted_at
            consumption = StockMovement.objects.filter(warehouse=document.warehouse, item=line.item,
                                                       document__kind__in=['sale', 'sale_return'])
            if since:
                consumption = consumption.filter(created_at__gt=since)
            line.consumption_quantity = max(ZERO, -(consumption.aggregate(total=Sum('quantity'))['total'] or ZERO))
            line.variance_quantity, line.variance_value = quantity, q(quantity * cost)
        elif document.kind in INBOUND_KINDS:
            if document.kind == 'opening' and balance.revision:
                raise ValidationError({'lines': _('%(item)s: boshlang‘ich qoldiq faqat birinchi harakat bo‘lishi mumkin.') % {'item': line.item_name}})
            quantity, cost = line.base_quantity, line.base_unit_cost
        else:
            quantity, cost = -line.base_quantity, balance.average_cost
            if not allow_negative and balance.quantity + quantity < 0:
                raise ValidationError({'lines': _('%(item)s: omborda yetarli qoldiq yo‘q.') % {'item': line.item_name}})
        line.base_unit_cost = cost
        if document.kind not in INBOUND_KINDS:
            input_factor = line.base_quantity / line.quantity if line.input_unit == 'purchase' and line.quantity else Decimal('1')
            line.unit_cost = q(cost * input_factor)
        line.save()
        movement = record_movement(document, line, quantity, cost)
        if document.kind in {'opening', 'stocktake'}:
            StockBalance.objects.filter(pk=balance.pk).update(last_counted_at=movement.created_at)
    return finish_document(document, actor)


@transaction.atomic
def reverse_document(document, reason, actor=None):
    document = StockDocument.objects.select_for_update().get(pk=document.pk)
    existing = StockDocument.objects.filter(reversal_of=document).first()
    if existing:
        return existing
    if document.status != 'posted' or document.kind not in MANUAL_KINDS:
        raise ValidationError(_('Faqat tasdiqlangan qo‘lda kiritilgan hujjatni teskari yozish mumkin.'))
    if not str(reason or '').strip():
        raise ValidationError({'reason': _('Teskari yozuv sababi majburiy.')})
    Warehouse.objects.select_for_update().get(pk=document.warehouse_id)
    reversal = make_document(document.restaurant, document.warehouse, 'reversal', actor,
                             reversal_of=document, reason=reason, reference=document.number,
                             responsible_name=actor_name(actor))
    for original in document.movements.select_related('line', 'item').all():
        balance = locked_balance(document.warehouse, original.item)
        if document.kind == 'stocktake' and balance.revision != original.revision:
            raise ValidationError(_('Sanashdan keyin harakatlar bor. Yangi inventarizatsiya bilan tuzating.'))
        line = StockDocumentLine.objects.create(document=reversal, item=original.item,
                    item_name=original.line.item_name, base_unit=original.line.base_unit,
                    quantity=abs(original.quantity), base_quantity=abs(original.quantity),
                    unit_cost=original.unit_cost, base_unit_cost=original.unit_cost,
                    expected_quantity=balance.quantity, expected_revision=balance.revision)
        record_movement(reversal, line, -original.quantity, original.unit_cost, exact_value=-original.value)
    document.status = 'reversed'
    document.save(update_fields=['status', 'updated_at'])
    if document.kind in {'opening', 'stocktake'}:
        for original in document.movements.all():
            latest = StockMovement.objects.filter(warehouse=document.warehouse, item_id=original.item_id,
                document__kind__in=['opening', 'stocktake'], document__status='posted').order_by('-created_at').first()
            StockBalance.objects.filter(warehouse=document.warehouse, item_id=original.item_id).update(
                last_counted_at=latest.created_at if latest else None)
    return finish_document(reversal, actor)


@transaction.atomic
def create_recipe(restaurant, data, actor=None):
    catalog_item = scoped(CatalogItem, restaurant, data.get('catalog_item'), 'catalogItem', is_active=True)
    CatalogItem.objects.select_for_update().get(pk=catalog_item.pk)
    if catalog_item.item_type != 'product':
        raise ValidationError({'catalogItem': _('Xizmat uchun ombor retsepti yaratilmaydi.')})
    yield_quantity = decimal(data.get('yield_quantity', 1), 'yieldQuantity', minimum=SIX)
    lines = data.get('lines')
    if not isinstance(lines, list) or not lines or len(lines) > 200:
        raise ValidationError({'lines': _('1 dan 200 tagacha ingredient kiriting.')})
    prepared, seen = [], set()
    for raw in lines:
        item = scoped(InventoryItem, restaurant, raw.get('item'), 'item', is_active=True)
        modifier = None
        if raw.get('modifier_option'):
            modifier = ModifierOption.objects.filter(pk=raw['modifier_option'], group__restaurant=restaurant,
                                                      group__catalog_items=catalog_item, is_active=True).first()
            if not modifier:
                raise ValidationError({'modifierOption': _('Modifikator taomga tegishli emas.')})
        unique = (str(item.pk), str(getattr(modifier, 'pk', '')))
        if unique in seen:
            raise ValidationError({'lines': _('Ingredient va modifikator juftligi takrorlanmasin.')})
        seen.add(unique)
        prepared.append(dict(item=item, quantity=decimal(raw.get('quantity'), minimum=SIX), modifier_option=modifier))
    version = (Recipe.objects.filter(catalog_item=catalog_item).aggregate(n=Max('version'))['n'] or 0) + 1
    Recipe.objects.filter(catalog_item=catalog_item, is_active=True).update(is_active=False)
    recipe = Recipe.objects.create(restaurant=restaurant, catalog_item=catalog_item, version=version,
                yield_quantity=yield_quantity, trigger=data.get('trigger', 'dispatch'), name=data.get('name', ''), created_by=actor)
    RecipeLine.objects.bulk_create([RecipeLine(recipe=recipe, **line) for line in prepared])
    return recipe


def components_for(recipe, quantity, modifier_ids):
    components = defaultdict(lambda: ZERO)
    for line in recipe.lines.all():
        if line.modifier_option_id is None or str(line.modifier_option_id) in modifier_ids:
            components[str(line.item_id)] += line.quantity * quantity / recipe.yield_quantity
    return {item_id: q(quantity) for item_id, quantity in components.items()}


@contextmanager
def inventory_replay_context(restaurant, snapshots=None, occurred_at=None):
    token = _replay.set({'restaurant': str(getattr(restaurant, 'pk', restaurant)),
                        'snapshots': snapshots or [], 'occurred_at': occurred_at})
    try:
        yield
    finally:
        _replay.reset(token)


def replay_recipe(order, item, recipe):
    context = _replay.get()
    if not context or context['restaurant'] != str(order.restaurant_id):
        return recipe, None, None
    snapshots = context['snapshots']
    if isinstance(snapshots, dict):
        snapshots = list(snapshots.values())
    if not isinstance(snapshots, list) or len(snapshots) > 1000:
        raise ValidationError(_('Offline ombor nusxasi noto‘g‘ri.'))
    if any(not isinstance(row, dict) for row in snapshots):
        raise ValidationError(_('Offline ombor qatori noto‘g‘ri.'))
    snapshot = next((row for row in snapshots if str(row.get('order_item_id', row.get('orderItemId'))) == str(item.pk)), None)
    warehouse = None
    if snapshot:
        recipe_id = snapshot.get('recipe_id', snapshot.get('recipeId'))
        try:
            recipe = Recipe.objects.filter(pk=recipe_id, restaurant_id=order.restaurant_id, catalog_item_id=item.catalog_item_id).prefetch_related('lines').first()
            version = int(snapshot.get('recipe_version', snapshot.get('recipeVersion', 0)))
        except (DjangoValidationError, ValueError, TypeError):
            raise ValidationError(_('Offline retsept versiyasi noto‘g‘ri.'))
        if not recipe or recipe.version != version:
            raise ValidationError(_('Offline retsept versiyasi topilmadi.'))
        if decimal(snapshot.get('quantity')) != item.quantity:
            raise ValidationError(_('Offline sarf miqdori buyurtmaga mos emas.'))
        expected = components_for(recipe, item.quantity, {str(v) for v in item.modifiers.values_list('modifier_option_id', flat=True)})
        component_rows = snapshot.get('components', [])
        if not isinstance(component_rows, list) or any(not isinstance(row, dict) for row in component_rows):
            raise ValidationError(_('Offline ingredient sarfi noto‘g‘ri.'))
        provided = {str(row.get('item_id', row.get('itemId'))): decimal(row.get('quantity')) for row in component_rows}
        if len(provided) != len(component_rows):
            raise ValidationError(_('Offline ingredient takrorlangan.'))
        if provided != expected:
            raise ValidationError(_('Offline ingredient sarfi retseptga mos emas.'))
        warehouse_id = snapshot.get('warehouse_id', snapshot.get('warehouseId'))
        if warehouse_id:
            warehouse = scoped(Warehouse, order.restaurant, warehouse_id, 'warehouse')
    occurred = context.get('occurred_at')
    if isinstance(occurred, str):
        occurred = parse_datetime(occurred)
    if occurred and timezone.is_naive(occurred):
        occurred = timezone.make_aware(occurred)
    if occurred and occurred > timezone.now() + timedelta(minutes=5):
        raise ValidationError(_('Offline hodisa sanasi kelajakda.'))
    return recipe, occurred, warehouse


@transaction.atomic
def consume_order_items(order, items, actor=None, *, trigger='dispatch', event_key=None):
    default_store = default_warehouse(order.restaurant)
    # Deterministic warehouse lock ordering also covers historic offline stores.
    list(Warehouse.objects.select_for_update().filter(restaurant=order.restaurant).order_by('pk'))
    results = []
    for item in items:
        if item.order_id != order.pk:
            raise ValidationError(_('Buyurtma qatori boshqa buyurtmaga tegishli.'))
        if item.catalog_item.item_type != 'product' or item.quantity <= 0:
            continue
        existing = OrderConsumption.objects.filter(order_item_id=item.pk).first()
        if existing:
            results.append(existing)
            continue
        recipe = Recipe.objects.filter(catalog_item=item.catalog_item, is_active=True).prefetch_related('lines').first()
        recipe, occurred, historical_warehouse = replay_recipe(order, item, recipe)
        warehouse = historical_warehouse or default_store
        if not recipe or recipe.trigger != trigger:
            continue
        components = components_for(recipe, item.quantity, {str(v) for v in item.modifiers.values_list('modifier_option_id', flat=True)})
        document = make_document(order.restaurant, warehouse, 'sale', actor,
                    reference=str(item.pk), reason='Retsept bo‘yicha sarf',
                    idempotency_key=f'sale:{item.pk}', **({'occurred_at': occurred} if occurred else {}))
        snapshot = []
        for item_id, quantity in sorted(components.items()):
            ingredient = InventoryItem.objects.get(pk=item_id, restaurant=order.restaurant)
            balance = locked_balance(warehouse, ingredient)
            replay = _replay.get()
            trusted_replay = replay and replay['restaurant'] == str(order.restaurant_id)
            if ingredient.availability_mode == 'block' and balance.quantity < quantity and not trusted_replay:
                raise ValidationError({'inventory': _('%(item)s: omborda yetarli qoldiq yo‘q.') % {'item': ingredient.name}})
            if occurred and balance.last_counted_at and occurred <= balance.last_counted_at:
                document.notes = 'late_after_count: Offline sarf oldingi sanashdan keyin sinxronlandi; qayta sanash kerak.'
                document.save(update_fields=['notes'])
            line = StockDocumentLine.objects.create(document=document, item=ingredient, item_name=ingredient.name,
                base_unit=ingredient.base_unit, quantity=quantity, base_quantity=quantity,
                unit_cost=balance.average_cost, base_unit_cost=balance.average_cost)
            movement = record_movement(document, line, -quantity, balance.average_cost, order_item=item.pk)
            snapshot.append({'item_id': item_id, 'quantity': str(quantity), 'unit_cost': str(movement.unit_cost)})
        finish_document(document, actor)
        results.append(OrderConsumption.objects.create(restaurant=order.restaurant, order_id=order.pk,
            order_item_id=item.pk, warehouse=warehouse, recipe=recipe, document=document,
            quantity=item.quantity, components=snapshot))
    return results


def has_consumption(item):
    return OrderConsumption.objects.filter(order_item_id=getattr(item, 'pk', item)).exists()


@transaction.atomic
def cancel_order_item(item, disposition='waste', actor=None, quantity=None, event_key=None):
    if disposition not in {'restore', 'not_prepared', 'returned', 'waste'}:
        raise ValidationError({'inventoryDisposition': _('not_prepared, returned yoki waste tanlang.')})
    consumption = OrderConsumption.objects.select_for_update().filter(order_item_id=item.pk).first()
    if not consumption:
        return None
    if consumption.restaurant_id != item.order.restaurant_id:
        raise ValidationError(_('Sarf boshqa restoranga tegishli.'))
    warehouse = Warehouse.objects.select_for_update().get(pk=consumption.warehouse_id)
    key = str(event_key or 'whole-item')
    previous = consumption.resolutions.filter(event_key=key).first()
    if previous:
        if previous.disposition != disposition or quantity is not None and previous.quantity != decimal(quantity):
            raise ValidationError(_('Qayta so‘rov oldingi bekor qilishga mos emas.'))
        return previous
    unresolved = consumption.quantity - consumption.resolved_quantity
    amount = decimal(quantity, minimum=SIX) if quantity is not None else unresolved
    if amount <= 0:
        return None
    if amount > unresolved:
        raise ValidationError(_('Qaytarilayotgan miqdor sarfdan ortiq.'))
    if quantity is not None and amount < unresolved and not event_key:
        raise ValidationError(_('Qisman qaytarishda takrorlanmaydigan hodisa kaliti majburiy.'))
    document = None
    if disposition != 'waste':
        document = make_document(consumption.restaurant, warehouse, 'sale_return', actor,
                   reason=disposition, reference=str(item.pk), idempotency_key=f'return:{consumption.pk}:{key}'[:200])
        for component in consumption.components:
            ingredient = InventoryItem.objects.get(pk=component['item_id'], restaurant=consumption.restaurant)
            # Cumulative rounding gives the final partial return the remaining
            # micro-unit and prevents repeated splits losing/creating stock.
            returned = (q(Decimal(component['quantity']) * (consumption.resolved_quantity + amount) / consumption.quantity)
                        - q(Decimal(component['quantity']) * consumption.resolved_quantity / consumption.quantity))
            cost = Decimal(component['unit_cost'])
            line = StockDocumentLine.objects.create(document=document, item=ingredient,
                item_name=ingredient.name, base_unit=ingredient.base_unit, quantity=returned,
                base_quantity=returned, unit_cost=cost, base_unit_cost=cost)
            record_movement(document, line, returned, cost, order_item=item.pk)
        finish_document(document, actor)
    result = ConsumptionResolution.objects.create(consumption=consumption, event_key=key,
                disposition=disposition, quantity=amount, document=document, created_by=actor, created_by_name=actor_name(actor))
    consumption.resolved_quantity += amount
    consumption.save(update_fields=['resolved_quantity', 'updated_at'])
    return result


@transaction.atomic
def split_consumption(original, replacement, removed_quantity, disposition='waste', actor=None, event_key=None):
    original_consumption = OrderConsumption.objects.select_for_update().filter(order_item_id=original.pk).first()
    if not original_consumption:
        return None
    existing = OrderConsumption.objects.filter(order_item_id=replacement.pk).first()
    if existing:
        if existing.source_consumption_id != original_consumption.pk:
            raise ValidationError(_('Yangi qator boshqa sarf bilan bog‘langan.'))
        return existing
    if replacement.order_id != original.order_id or replacement.catalog_item_id != original.catalog_item_id:
        raise ValidationError(_('Qoldiq qatori asl taomga tegishli bo‘lishi kerak.'))
    removed = decimal(removed_quantity, minimum=SIX)
    remaining = original_consumption.quantity - original_consumption.resolved_quantity - removed
    if remaining <= 0 or replacement.quantity != remaining:
        raise ValidationError(_('Qisman bekor qilish miqdorlari mos emas.'))
    cancel_order_item(original, disposition, actor, removed, event_key or f'split:{replacement.pk}')
    components = [{**row, 'quantity': str(q(Decimal(row['quantity']) - q(Decimal(row['quantity']) * (original_consumption.quantity - remaining) / original_consumption.quantity)))}
                  for row in original_consumption.components]
    result = OrderConsumption.objects.create(restaurant=original_consumption.restaurant,
             order_id=replacement.order_id, order_item_id=replacement.pk, warehouse=original_consumption.warehouse,
             recipe=original_consumption.recipe, document=original_consumption.document,
             quantity=remaining, components=components, source_consumption=original_consumption)
    # Allocation closes the original lineage; the replacement now owns all remaining returns.
    ConsumptionResolution.objects.create(consumption=original_consumption, event_key=f'allocate:{replacement.pk}',
                  disposition='allocated', quantity=remaining, created_by=actor, created_by_name=actor_name(actor))
    original_consumption.resolved_quantity = original_consumption.quantity
    original_consumption.save(update_fields=['resolved_quantity', 'updated_at'])
    return result


def empty_menu_inventory():
    return {'tracked': False, 'blocked': False, 'low_stock': False, 'available_quantity': None,
            'reason': '', 'updated_at': None}


def _recipe_availability(recipe, balances, modifier_options=None):
    result = empty_menu_inventory()
    catalog_item = recipe.catalog_item
    result['tracked'] = True
    requirements = components_for(recipe, Decimal('1'), {str(getattr(value, 'pk', value)) for value in (modifier_options or [])})
    ingredients = {str(row.item_id): row.item for row in recipe.lines.all()}
    minimum_sale_quantity = sale_quantity_step(catalog_item.sale_unit)
    available, reasons = [], []
    for ingredient_id, required in requirements.items():
        ingredient = ingredients[ingredient_id]
        if ingredient.availability_mode == 'off' or required <= 0:
            continue
        balance = balances.get(ingredient_id)
        quantity = balance.quantity if balance else ZERO
        available.append(max(ZERO, q(quantity / required)))
        if quantity < required * minimum_sale_quantity or quantity <= ingredient.min_quantity:
            result['low_stock'] = True
            reasons.append(ingredient.name)
        if ingredient.availability_mode == 'block' and quantity < required * minimum_sale_quantity:
            result['blocked'] = True
        if balance and (not result['updated_at'] or balance.updated_at > result['updated_at']):
            result['updated_at'] = balance.updated_at
    result['available_quantity'] = str(min(available)) if available else None
    result['reason'] = ', '.join(reasons)
    return result


def menu_inventory_map(restaurant, catalog_item_ids=None):
    """One menu response, five bounded queries regardless of menu item count."""
    restaurant_id = getattr(restaurant, 'pk', restaurant)
    recipes = Recipe.objects.filter(restaurant_id=restaurant_id, is_active=True,
                catalog_item__item_type='product').select_related('catalog_item').prefetch_related('lines__item')
    if catalog_item_ids is not None:
        recipes = recipes.filter(catalog_item_id__in=catalog_item_ids)
    warehouse = Warehouse.objects.filter(restaurant_id=restaurant_id, is_default=True, is_active=True).first()
    balances = {str(row.item_id): row for row in StockBalance.objects.filter(warehouse=warehouse)} if warehouse else {}
    return {str(recipe.catalog_item_id): _recipe_availability(recipe, balances) for recipe in recipes}


def get_menu_inventory(catalog_item, modifier_options=None):
    if catalog_item.item_type != 'product':
        return empty_menu_inventory()
    if not modifier_options:
        return menu_inventory_map(catalog_item.restaurant_id, [catalog_item.pk]).get(str(catalog_item.pk), empty_menu_inventory())
    recipe = Recipe.objects.filter(catalog_item=catalog_item, is_active=True).select_related('catalog_item').prefetch_related('lines__item').first()
    if not recipe:
        return empty_menu_inventory()
    warehouse = Warehouse.objects.filter(restaurant_id=catalog_item.restaurant_id, is_default=True, is_active=True).first()
    balances = {str(row.item_id): row for row in StockBalance.objects.filter(warehouse=warehouse)} if warehouse else {}
    return _recipe_availability(recipe, balances, modifier_options)


def validate_catalog_stock(catalog_item, quantity, modifier_options=None):
    """Early POS selection feedback; confirmed dispatch rechecks under locks."""
    context = _replay.get()
    if context and context['restaurant'] == str(catalog_item.restaurant_id):
        return
    if catalog_item.item_type != 'product':
        return
    recipe = Recipe.objects.filter(catalog_item=catalog_item, is_active=True).prefetch_related('lines__item').first()
    if not recipe:
        return
    quantity = decimal(quantity, minimum=SIX)
    modifier_ids = {str(getattr(value, 'pk', value)) for value in (modifier_options or [])}
    requirements = components_for(recipe, quantity, modifier_ids)
    warehouse = Warehouse.objects.filter(restaurant_id=catalog_item.restaurant_id, is_default=True, is_active=True).first()
    balances = {str(row.item_id): row.quantity for row in StockBalance.objects.filter(warehouse=warehouse, item_id__in=requirements)}
    ingredients = {str(line.item_id): line.item for line in recipe.lines.all()}
    for ingredient_id, required in requirements.items():
        ingredient = ingredients[ingredient_id]
        if ingredient.availability_mode == 'block' and balances.get(ingredient_id, ZERO) < required:
            raise ValidationError({'inventory': _('%(item)s: tanlangan miqdor uchun qoldiq yetarli emas.') % {'item': ingredient.name}})


def inventory_snapshot(restaurant):
    warehouse = Warehouse.objects.filter(restaurant=restaurant, is_default=True, is_active=True).first()
    warehouses = list(Warehouse.objects.filter(restaurant=restaurant, is_active=True))
    recipes = Recipe.objects.filter(restaurant=restaurant, is_active=True).select_related('catalog_item').prefetch_related('lines')
    from apps.sales.models import Order
    active_order_ids = Order.objects.filter(restaurant=restaurant).exclude(status__in=['closed', 'cancelled']).values_list('pk', flat=True)
    consumptions = OrderConsumption.objects.filter(restaurant=restaurant, order_id__in=active_order_ids).select_related('recipe')
    return {'version': 1, 'updated_at': timezone.now().isoformat(), 'warehouse_id': str(warehouse.pk) if warehouse else None,
        'warehouses': [{'id': str(row.pk), 'name': row.name, 'is_default': row.is_default} for row in warehouses],
        'items': [{'id': str(row.pk), 'name': row.name, 'base_unit': row.base_unit,
                   'availability_mode': row.availability_mode, 'min_quantity': str(row.min_quantity)}
                  for row in InventoryItem.objects.filter(restaurant=restaurant)],
        'balances': [{'warehouse_id': str(row.warehouse_id), 'item_id': str(row.item_id), 'quantity': str(row.quantity),
                      'revision': row.revision} for row in StockBalance.objects.filter(warehouse__restaurant=restaurant)],
        'recipes': [{'id': str(row.pk), 'catalog_item_id': str(row.catalog_item_id), 'version': row.version,
                     'yield_quantity': str(row.yield_quantity), 'trigger': row.trigger, 'sale_unit': row.catalog_item.sale_unit,
                     'lines': [{'item_id': str(line.item_id), 'quantity': str(line.quantity),
                                'modifier_option_id': str(line.modifier_option_id) if line.modifier_option_id else None}
                               for line in row.lines.all()]} for row in recipes],
        'consumptions': [{'order_item_id': str(row.order_item_id), 'recipe_id': str(row.recipe_id),
                          'recipe_version': row.recipe.version, 'quantity': str(row.quantity),
                          'resolved_quantity': str(row.resolved_quantity), 'warehouse_id': str(row.warehouse_id),
                          'components': [{'item_id': part['item_id'], 'quantity': part['quantity']} for part in row.components]}
                         for row in consumptions]}
