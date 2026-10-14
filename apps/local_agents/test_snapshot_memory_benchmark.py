"""Opt-in, disposable local benchmark; no production database is used."""
import gc
import hashlib
import json
import os
import subprocess
import sys
import time
import tracemalloc
import types
from datetime import timedelta
from pathlib import Path
from unittest import skipUnless
from unittest.mock import patch

from django.db.models import Prefetch
from django.utils import timezone
from rest_framework.renderers import JSONRenderer

from apps.billing.models import Payment
from apps.catalog.models import CatalogCategory, CatalogItem
from apps.catalog.serializers import CatalogMenuCategorySerializer
from apps.catalog.selectors import active_modifier_assignments_prefetch
from apps.local_agents.sync import _menu_snapshot
from apps.sales.models import Order, OrderItem
from apps.sales.selectors.orders import pos_order_queryset
from apps.sales.serializers import OrderSerializer
from apps.sales.tests.support.pos_api import PosTestCase


def measure(build):
    gc.collect()
    tracemalloc.start()
    started = time.perf_counter()
    data = build()
    encoded = JSONRenderer().render(data)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    result = {'peakMiB': round(peak / 1024**2, 2), 'seconds': round(time.perf_counter() - started, 3),
              'sha256': hashlib.sha256(encoded).hexdigest(), 'bytes': len(encoded)}
    del data, encoded
    gc.collect()
    return result


@skipUnless(os.environ.get('RUN_SNAPSHOT_MEMORY_BENCHMARK') == '1', 'Opt-in memory benchmark')
class SnapshotMemoryBenchmark(PosTestCase):
    def test_same_response_with_shared_catalog_graph(self):
        self.category.is_active = False
        self.category.save(update_fields=['is_active'])
        frozen = timezone.now()
        raw = {'cashSale': 2, 'packages': [
            {'code': 1378885 + index, 'isUnitPackage': '1' if index == 561 else '2',
             'name': 'x' * 250, 'unitName': 'dona', 'children': ['x' * 40], 'childrenValue': ['1']}
            for index in range(562)
        ]}
        small_raw = {'label': 0, 'unitCode': 796, 'packages': [
            {'code': 1000 + index, 'name': 'x' * 680, 'isUnitPackage': '1' if index == 0 else '2'}
            for index in range(25)
        ]}
        categories = CatalogCategory.objects.bulk_create([
            CatalogCategory(restaurant=self.restaurant, name=f'Benchmark category {index}',
                            prep_station=self.prep_station, mxik_payload=raw, sort_order=index)
            for index in range(20)
        ])
        products = CatalogItem.objects.bulk_create([
            CatalogItem(restaurant=self.restaurant, category=categories[index % 20], prep_station=self.prep_station,
                        name=f'Benchmark product {index}', name_uz=f'Benchmark product {index}', price=1000,
                        mxik_payload=small_raw if index < 31 else {}, sort_order=index)
            for index in range(301)
        ])
        orders = Order.objects.bulk_create([
            Order(restaurant=self.restaurant, distribution_point=self.takeaway_distribution,
                  opened_by=self.user, cashier=self.user, order_number=10000 + index,
                  channel=Order.Channel.TAKEAWAY, status=Order.Status.CLOSED,
                  subtotal=10000, total=10000, closed_at=frozen - timedelta(days=5))
            for index in range(330)
        ])
        OrderItem.objects.bulk_create([
            OrderItem(order=orders[index % 330], catalog_item=products[index % 31],
                      prep_station=self.prep_station, created_by=self.user, quantity=1,
                      base_unit_price=1000, unit_price=1000, line_total=1000)
            for index in range(3521)
        ])
        shift = self.create_cash_shift()
        Payment.objects.bulk_create([
            Payment(order=order, cash_shift=shift, cash_desk=self.cash_desk, received_by=self.user,
                    method=Payment.Method.CASH, amount=10000, status=Payment.Status.SUCCEEDED)
            for order in orders
        ])
        # Pin the production baseline so committing this fix does not change it.
        baseline = types.ModuleType('snapshot_memory_baseline')
        sys.modules[baseline.__name__] = baseline
        source = subprocess.check_output([
            'git', 'show',
            'c1a5b50780fd3e94550cc73f4887393f884851c4:apps/sales/selectors/orders.py',
        ], text=True)
        exec(compile(source, '<production selector>', 'exec'), baseline.__dict__)

        def legacy_menu():
            items = CatalogItem.objects.filter(is_active=True, is_stoplisted=False).select_related(
                'category__prep_station', 'prep_station').prefetch_related(active_modifier_assignments_prefetch())
            rows = CatalogCategory.objects.filter(restaurant=self.restaurant, is_active=True).select_related('prep_station').prefetch_related(
                Prefetch('items', queryset=items, to_attr='active_menu_items')).order_by('sort_order', 'name')
            return CatalogMenuCategorySerializer(rows, many=True, context={'offline_translations': True}).data

        ids = [order.pk for order in orders]
        with patch('django.utils.timezone.now', return_value=frozen):
            old_menu = measure(legacy_menu)
            new_menu = measure(lambda: _menu_snapshot(self.restaurant))
            old_orders = measure(lambda: OrderSerializer(baseline.pos_order_queryset(Order.objects.filter(pk__in=ids)).order_by('created_at'), many=True).data)
            new_orders = measure(lambda: OrderSerializer(pos_order_queryset(Order.objects.filter(pk__in=ids)).order_by('created_at'), many=True).data)
        self.assertEqual(old_menu['sha256'], new_menu['sha256'])
        self.assertEqual(old_orders['sha256'], new_orders['sha256'])
        result = {'environment': 'Disposable SQLite synthetic fixture', 'products': 301, 'categories': 20,
                  'orderCount': 330, 'orderItems': 3521, 'distinctOrderedProducts': 31,
                  'menu': {'before': old_menu, 'after': new_menu}, 'orders': {'before': old_orders, 'after': new_orders}}
        destination = Path(os.environ['SNAPSHOT_MEMORY_BENCHMARK_OUTPUT'])
        destination.write_text(json.dumps(result, indent=2), encoding='utf-8')
        print(json.dumps(result), flush=True)
