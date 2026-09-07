from datetime import timedelta
from collections import defaultdict
from decimal import Decimal

from django.db.models import Q, Sum
from django.utils import timezone

from .models import InventoryItem, StockBalance, StockDocument, StockDocumentLine, StockMovement, Warehouse
from .services import ZERO, q


def balances(restaurant, warehouse=None):
    warehouses_query = Warehouse.objects.filter(restaurant=restaurant)
    if warehouse:
        warehouses_query = warehouses_query.filter(pk=warehouse.pk)
    else:
        warehouses_query = warehouses_query.filter(Q(is_active=True) | Q(stockbalance__quantity__gt=0) | Q(stockbalance__quantity__lt=0)).distinct()
    warehouses = list(warehouses_query)
    items = list(InventoryItem.objects.filter(restaurant=restaurant).filter(Q(is_active=True) | Q(stockbalance__quantity__gt=0) | Q(stockbalance__quantity__lt=0)).distinct())
    current = {(row.warehouse_id, row.item_id): row for row in StockBalance.objects.filter(warehouse__in=warehouses)}
    result = []
    for store in warehouses:
        for item in items:
            row = current.get((store.pk, item.pk))
            quantity = row.quantity if row else ZERO
            result.append({'item': str(item.pk), 'item_name': item.name, 'sku': item.sku,
                'base_unit': item.base_unit, 'warehouse': str(store.pk), 'warehouse_name': store.name,
                'quantity': str(quantity), 'average_cost': str(row.average_cost if row else ZERO),
                'value': str(row.value if row else ZERO), 'min_quantity': str(item.min_quantity),
                'availability_mode': item.availability_mode, 'is_low': quantity <= item.min_quantity,
                'is_negative': quantity < 0, 'last_counted_at': row.last_counted_at if row else None,
                'updated_at': row.updated_at if row else None})
    return result


def movements_queryset(restaurant, warehouse=None, start=None, end=None, item=None, kind=None):
    queryset = StockMovement.objects.filter(document__restaurant=restaurant).select_related('document', 'item', 'line')
    if warehouse:
        queryset = queryset.filter(warehouse=warehouse)
    if start:
        queryset = queryset.filter(occurred_at__gte=start)
    if end:
        queryset = queryset.filter(occurred_at__lt=end)
    if item:
        queryset = queryset.filter(item=item)
    if kind:
        queryset = queryset.filter(document__kind=kind)
    return queryset


def movements(restaurant, warehouse=None, start=None, end=None, item=None, kind=None, limit=200, offset=0):
    rows = movements_queryset(restaurant, warehouse, start, end, item, kind)
    if limit is not None:
        rows = rows[offset:offset + limit]
    return [{'id': str(row.pk), 'document': str(row.document_id), 'document_number': row.document.number,
             'kind': row.document.kind, 'item': str(row.item_id), 'item_name': row.line.item_name,
             'base_unit': row.line.base_unit, 'warehouse': str(row.warehouse_id), 'quantity': str(row.quantity),
             'unit_cost': str(row.unit_cost), 'value': str(row.value), 'valuation_adjustment': str(row.valuation_adjustment),
             'balance_after': str(row.balance_after), 'occurred_at': row.occurred_at,
             'created_at': row.created_at, 'order_item': str(row.order_item) if row.order_item else None} for row in rows]


def variance(restaurant, warehouse=None, start=None, end=None):
    rows = StockDocumentLine.objects.filter(document__restaurant=restaurant, document__kind='stocktake', document__status='posted').select_related('document')
    if warehouse:
        rows = rows.filter(document__warehouse=warehouse)
    if start:
        rows = rows.filter(document__occurred_at__gte=start)
    if end:
        rows = rows.filter(document__occurred_at__lt=end)
    result = []
    for line in rows.order_by('-document__posted_at'):
        percent = q(abs(line.variance_quantity) / line.consumption_quantity * 100) if line.consumption_quantity else None
        checks = []
        if line.tolerance_percent > 0 and percent is not None:
            checks.append(percent > line.tolerance_percent)
        if line.tolerance_quantity > 0:
            checks.append(abs(line.variance_quantity) > line.tolerance_quantity)
        if line.tolerance_value > 0:
            checks.append(abs(line.variance_value) > line.tolerance_value)
        attention = bool(line.variance_quantity and (any(checks) if checks else True))
        result.append({'document': str(line.document_id), 'document_number': line.document.number,
                'occurred_at': line.document.occurred_at, 'item': str(line.item_id), 'item_name': line.item_name,
                'base_unit': line.base_unit, 'expected_quantity': str(line.expected_quantity),
                'actual_quantity': str(line.base_quantity), 'variance_quantity': str(line.variance_quantity),
                'variance_value': str(line.variance_value), 'consumption_quantity': str(line.consumption_quantity),
                'variance_percent': str(percent) if percent is not None else None,
                'tolerance_percent': str(line.tolerance_percent), 'tolerance_quantity': str(line.tolerance_quantity),
                'tolerance_value': str(line.tolerance_value), 'requires_attention': attention})
    return result


def overview(restaurant, warehouse=None, start=None, end=None):
    current = balances(restaurant, warehouse)
    queryset = movements_queryset(restaurant, warehouse, start, end)
    grouped = {row['document__kind']: row['total'] or ZERO for row in queryset.values('document__kind').annotate(total=Sum('value'))}
    differences = variance(restaurant, warehouse, start, end)
    counts = [row['last_counted_at'] for row in current if row['last_counted_at']]
    return {'stock_value': str(sum((Decimal(row['value']) for row in current), ZERO)),
            'item_count': len({row['item'] for row in current}),
            'low_stock_count': sum(row['is_low'] for row in current),
            'negative_stock_count': sum(row['is_negative'] for row in current),
            'receipt_value': str(grouped.get('receipt', ZERO)),
            'issue_value': str(abs(grouped.get('issue', ZERO))),
            'sale_cost': str(abs(grouped.get('sale', ZERO) + grouped.get('sale_return', ZERO))),
            'variance_value': str(sum((Decimal(row['variance_value']) for row in differences), ZERO)),
            'variance_quantity_count': sum(bool(Decimal(row['variance_quantity'])) for row in differences),
            'last_counted_at': max(counts) if counts else None}


def insights(restaurant, warehouse=None):
    now = timezone.now()
    current = balances(restaurant, warehouse)
    result = []

    def add(code, severity, title, detail, item, evidence, recommendation):
        result.append({'id': code, 'severity': severity, 'title': title, 'detail': detail,
                       'item': item, 'evidence': evidence, 'recommendation': recommendation})

    for row in current:
        if row['is_negative']:
            add(f'negative:{row["warehouse"]}:{row["item"]}', 'critical', f'{row["item_name"]}: manfiy qoldiq',
                'Nazariy sarf kiritilgan zaxiradan oshgan. Bu o‘zi o‘g‘irlik dalili emas.', row['item'],
                {'quantity': row['quantity'], 'base_unit': row['base_unit'], 'warehouse': row['warehouse']},
                'Kiritilmagan kirim, retsept normasi va oxirgi sanashni tekshiring.')
        elif row['is_low']:
            add(f'low:{row["warehouse"]}:{row["item"]}', 'warning', f'{row["item_name"]}: zaxira kamaygan',
                'Qoldiq sozlangan minimumdan oshmaydi.', row['item'],
                {'quantity': row['quantity'], 'min_quantity': row['min_quantity'], 'warehouse': row['warehouse']},
                'Mavjud mahsulotni tekshirib, xaridni rejalashtiring.')
    recent = movements_queryset(restaurant, warehouse, now - timedelta(days=14)).filter(document__kind__in=['sale', 'sale_return'])
    consumed = {(str(row['warehouse_id']), str(row['item_id'])): max(ZERO, -row['total']) for row in
                recent.values('warehouse_id', 'item_id').annotate(total=Sum('quantity'))}
    for row in current:
        total = consumed.get((row['warehouse'], row['item']), ZERO)
        if total > 0 and Decimal(row['quantity']) > 0:
            days = q(Decimal(row['quantity']) / (total / 14))
            if days <= 3:
                add(f'runway:{row["warehouse"]}:{row["item"]}', 'warning', f'{row["item_name"]}: yaqin kunlarda tugashi mumkin',
                    'Oxirgi 14 kundagi retsept sarfi bo‘yicha taxmin; kelajakdagi talab o‘zgarishi mumkin.', row['item'],
                    {'days_remaining': str(days), 'period_days': 14, 'consumption_quantity': str(total),
                     'quantity': row['quantity'], 'warehouse': row['warehouse']}, 'Yetkazib berish muddatini hisobga olib xarid buyurtmasini tayyorlang.')
    recent_variance = variance(restaurant, warehouse, now - timedelta(days=30))
    for row in recent_variance:
        if row['requires_attention']:
            add(f'variance:{row["document"]}:{row["item"]}', 'warning', f'{row["item_name"]}: sanashda og‘ish',
                'Haqiqiy qoldiq hisobdagi qoldiqdan farq qiladi. Sabab hali tasdiqlanmagan.', row['item'],
                row, 'Retsept, o‘lchov birligi, buzilish va boshqa chiqim hujjatlarini solishtiring.')
    monthly = defaultdict(list)
    for row in recent_variance:
        monthly[row['item']].append(row)
    for item_id, rows in monthly.items():
        if len(rows) < 2:
            continue
        shortages = sum((-Decimal(row['variance_quantity']) for row in rows if Decimal(row['variance_quantity']) < 0), ZERO)
        lost_value = sum((-Decimal(row['variance_value']) for row in rows if Decimal(row['variance_quantity']) < 0), ZERO)
        example = rows[0]
        if shortages > Decimal(example['tolerance_quantity']) and shortages > 0:
            add(f'monthly-variance:{item_id}', 'warning', f'{example["item_name"]}: takroriy kamomadlar yig‘ilgan',
                'Oxirgi 30 kundagi sanash kamomadlari yig‘indisi. Alohida kichik farqlar ham jamlanadi.', item_id,
                {'quantity': str(shortages), 'variance_value': str(-lost_value), 'period_days': 30,
                 'documents': [row['document'] for row in rows], 'count_count': len(rows)},
                'Muntazam kichik og‘ish sababini retsept va chiqim qaydlari bilan tekshiring.')
    receipts = StockDocumentLine.objects.filter(document__restaurant=restaurant, document__kind='receipt',
                  document__status='posted').select_related('document').order_by('-document__posted_at')
    if warehouse:
        receipts = receipts.filter(document__warehouse=warehouse)
    recent_prices = defaultdict(list)
    for line in receipts:
        if len(recent_prices[line.item_id]) < 2:
            recent_prices[line.item_id].append(line)
    for item_id, lines in recent_prices.items():
        if len(lines) != 2 or lines[1].base_unit_cost <= 0 or lines[0].base_unit_cost <= lines[1].base_unit_cost:
            continue
        increase = q((lines[0].base_unit_cost / lines[1].base_unit_cost - 1) * 100)
        if increase < 5:
            continue
        from .models import RecipeLine
        affected = list(RecipeLine.objects.filter(item_id=item_id, recipe__is_active=True).values_list('recipe__catalog_item__name', flat=True).distinct())
        add(f'price:{item_id}', 'info', f'{lines[0].item_name}: xarid tannarxi oshgan',
            'Oxirgi ikki tasdiqlangan kirim asosiy birlik tannarxlari solishtirildi.', str(item_id),
            {'previous_cost': str(lines[1].base_unit_cost), 'latest_cost': str(lines[0].base_unit_cost),
             'cost_increase_percent': str(increase), 'affected_dishes': affected,
             'documents': [str(line.document_id) for line in lines]},
            'Ta’sirlangan taomlar ingredient tannarxini va keyingi xarid narxini ko‘rib chiqing.')
    expiring = StockDocumentLine.objects.filter(document__restaurant=restaurant, document__kind='receipt',
                 document__status='posted', expires_on__lte=timezone.localdate() + timedelta(days=3)).select_related('document')
    if warehouse:
        expiring = expiring.filter(document__warehouse=warehouse)
    positive_items = {(row['warehouse'], row['item']) for row in current if Decimal(row['quantity']) > 0}
    for line in expiring[:100]:
        if (str(line.document.warehouse_id), str(line.item_id)) not in positive_items:
            continue
        add(f'expiry:{line.pk}', 'warning', f'{line.item_name}: partiya muddatini tekshiring',
            'Kirim partiyasida muddati yaqin yoki o‘tgan sana bor. Partiya bo‘yicha aniq qoldiq hisoblanmagan.', str(line.item_id),
            {'document': str(line.document_id), 'document_number': line.document.number,
             'expires_on': line.expires_on.isoformat(), 'lot_number': line.lot_number},
            'Shu partiyadan mahsulot qolganini tekshiring; muddati o‘tgan mahsulotni ishlatmang.')
    late = StockDocument.objects.filter(restaurant=restaurant, notes__startswith='late_after_count:', posted_at__gte=now - timedelta(days=30))
    if warehouse:
        late = late.filter(warehouse=warehouse)
    for document in late[:100]:
        item_ids = list(document.movements.values_list('item_id', flat=True))
        reconciled = StockBalance.objects.filter(warehouse=document.warehouse, item_id__in=item_ids, last_counted_at__gt=document.posted_at).count()
        if item_ids and reconciled == len(set(item_ids)):
            continue
        add(f'late:{document.pk}', 'critical', 'Offline sarf sanashdan keyin kelgan',
            'Oldingi sanashdagi qoldiq bilan kech kelgan sarf o‘zaro tekshirilishi kerak.', None,
            {'document': str(document.pk), 'document_number': document.number, 'occurred_at': document.occurred_at,
             'posted_at': document.posted_at}, 'Ta’sirlangan mahsulotlarni qayta sanab, yangi inventarizatsiya tasdiqlang.')
    from .ai import ai_available
    return {'mode': 'rules', 'ai_available': bool(ai_available()), 'generated_at': now, 'items': result}
