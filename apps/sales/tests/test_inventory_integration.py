"""Inventory behavior through real POS, kitchen, billing and Agent entry points."""

from decimal import Decimal
import uuid
from unittest.mock import patch

from rest_framework.test import APIClient

from apps.billing.models import Payment
from apps.billing.services import OrderPaymentService
from apps.catalog.models import CatalogItemModifierGroup, ModifierGroup, ModifierOption
from apps.inventory.models import (
    ConsumptionResolution, InventoryItem, OrderConsumption, StockBalance,
    StockDocument, StockMovement, Warehouse,
)
from apps.inventory.services import create_document, create_recipe, post_document
from apps.kitchen.models import KitchenTicket, KitchenTicketLine
from apps.local_agents.models import LocalAgent
from apps.local_agents.tests_support import bind_agent_client
from apps.printing.models import PrintDocument
from apps.sales.models import Order, OrderItem
from apps.sales.services import OrderStateService
from apps.sales.services.marking import OrderMarkingScanService
from apps.sales.tests.support.pos_api import PosAPITestCase


class LegacyInventoryCompatibilityTests(PosAPITestCase):
    def test_unconfigured_old_agent_dispatch_without_inventory_fields_still_succeeds(self):
        order = self.create_order_via_api({'channel': 'takeaway', 'guest_count': 1})
        self.add_item_via_api(order['id'], quantity=1)
        agent, token = LocalAgent.issue_for_restaurant(restaurant=self.restaurant, name='Legacy 2.0.4')
        client = APIClient()
        bind_agent_client(client, agent, token)
        operation = {
            'operationId': 'legacy-no-inventory-dispatch', 'userId': str(self.user.pk),
            'method': 'POST', 'path': f"/api/v1/pos/sales/orders/{order['id']}/submit/", 'body': {},
        }
        for replayed in (False, True):
            response = client.post('/api/v1/local-agent/sync/mutations/', {'operations': [operation]},
                                   format='json', HTTP_AUTHORIZATION=f'Bearer {token}')
            self.assertEqual(response.status_code, 200, response.data)
            result = response.data['results'][0]
            self.assertEqual(result['status'], 200, result)
            self.assertEqual(result['replayed'], replayed)
        self.assertFalse(OrderConsumption.objects.exists())
        self.assertFalse(StockMovement.objects.exists())
        self.assertFalse(StockBalance.objects.exists())


class InventoryPOSIntegrationTests(PosAPITestCase):
    permission_codes = PosAPITestCase.permission_codes + (
        'pos_fiscal_receipts.skip', 'pos_kitchen_orders.cancel',
    )

    def setUp(self):
        super().setUp()
        self.warehouse = Warehouse.objects.create(
            restaurant=self.restaurant, name='Asosiy ombor', is_default=True,
        )
        self.ingredient = InventoryItem.objects.create(
            restaurant=self.restaurant, name='Kartoshka', base_unit='g',
            purchase_unit='kg', purchase_factor=1000, availability_mode='block',
            min_quantity=100,
        )
        opening = create_document(self.restaurant, {
            'kind': 'opening', 'warehouse': str(self.warehouse.pk),
            'reference': 'INITIAL-001', 'responsible_name': 'Omborchi',
            'lines': [{'item': str(self.ingredient.pk), 'quantity': '1000', 'unit_cost': '10'}],
        }, actor=self.user)
        post_document(opening, actor=self.user)
        self.recipe = self.new_recipe('100')

    def new_recipe(self, quantity, **overrides):
        return create_recipe(self.restaurant, {
            'catalog_item': str(self.catalog_item.pk), 'yield_quantity': '1',
            'lines': [{'item': str(self.ingredient.pk), 'quantity': quantity}],
            **overrides,
        }, actor=self.user)

    def create_order(self, quantity=1):
        payload = self.create_order_via_api({'channel': 'takeaway', 'guest_count': 1})
        item = self.add_item_via_api(payload['id'], quantity=quantity)
        return Order.objects.get(pk=payload['id']), OrderItem.objects.get(pk=item['id'])

    def assert_stock(self, quantity):
        balance = StockBalance.objects.get(warehouse=self.warehouse, item=self.ingredient)
        self.assertEqual(balance.quantity, Decimal(quantity))
        return balance

    def delete_item(self, item, disposition):
        return self.client.delete(
            f'/api/v1/pos/sales/orders/items/{item.pk}/',
            {'inventoryDisposition': disposition}, format='json',
        )

    def agent_client(self):
        agent, token = LocalAgent.issue_for_restaurant(
            restaurant=self.restaurant, name='Inventory integration coordinator',
        )
        client = APIClient()
        bind_agent_client(client, agent, token)
        return client, token

    def replay_snapshot(self, item, *, recipe=None, quantity=None):
        recipe = recipe or self.recipe
        return {
            str(item.pk): {
                'orderItemId': str(item.pk), 'recipeId': str(recipe.pk),
                'recipeVersion': recipe.version, 'warehouseId': str(self.warehouse.pk),
                'quantity': str(item.quantity), 'resolvedQuantity': '0',
                'components': [{
                    'itemId': str(self.ingredient.pk),
                    'quantity': quantity or str(Decimal('100') * item.quantity),
                }],
            },
        }

    def test_confirmed_dispatch_consumes_once_and_exposes_boolean_to_pos(self):
        order, item = self.create_order(2)
        self.assert_stock('1000')
        first = self.submit_order_via_api(order.pk)
        self.assert_stock('800')
        self.assertTrue(first['items'][0]['inventory_consumed'])
        consumption = OrderConsumption.objects.get(order_item_id=item.pk)
        self.assertEqual(consumption.recipe_id, self.recipe.pk)
        self.assertEqual(consumption.quantity, 2)
        self.assertEqual(Decimal(consumption.components[0]['quantity']), 200)
        self.submit_order_via_api(order.pk)
        self.assert_stock('800')
        self.assertEqual(OrderConsumption.objects.filter(order_item_id=item.pk).count(), 1)
        self.assertEqual(StockDocument.objects.filter(kind='sale').count(), 1)
        self.assertEqual(KitchenTicketLine.objects.filter(order_item=item).count(), 1)
        get = self.client.get(f'/api/v1/pos/sales/orders/{order.pk}/')
        self.assertEqual(get.status_code, 200, get.data)
        self.assertTrue(get.json()['items'][0]['inventoryConsumed'])

    def test_aggregate_shortage_rolls_back_entire_submit_and_kitchen_batch(self):
        order, item = self.create_order(7)
        self.add_item_via_api(order.pk, quantity=4)
        response = self.client.post(f'/api/v1/pos/sales/orders/{order.pk}/submit/', {}, format='json')
        self.assertEqual(response.status_code, 400, response.data)
        self.assert_stock('1000')
        self.assertFalse(OrderConsumption.objects.exists())
        self.assertFalse(StockDocument.objects.filter(kind='sale').exists())
        self.assertFalse(KitchenTicket.objects.filter(order=order).exists())
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.OPEN)
        item.refresh_from_db()
        self.assertEqual(item.status, OrderItem.Status.NEW)

    def test_stock_shortage_localizes_real_pos_add_and_dispatch_errors(self):
        order, item = self.create_order(7)
        self.add_item_via_api(order.pk, quantity=4)
        expected = {
            'uz': ('Kartoshka: tanlangan miqdor uchun qoldiq yetarli emas.',
                   'Kartoshka: omborda yetarli qoldiq yo‘q.'),
            'ru': ('Kartoshka: остатка недостаточно для выбранного количества.',
                   'Kartoshka: недостаточный остаток на складе.'),
            'uz-crl': ('Kartoshka: танланган миқдор учун қолдиқ етарли эмас.',
                       'Kartoshka: омборда етарли қолдиқ йўқ.'),
        }
        for language, (add_message, dispatch_message) in expected.items():
            with self.subTest(language=language):
                response = self.client.post(f'/api/v1/pos/sales/orders/{order.pk}/items/',
                            {'catalogItem': str(self.catalog_item.pk), 'quantity': 11},
                            format='json', HTTP_ACCEPT_LANGUAGE=language)
                self.assertEqual(response.status_code, 400, response.data)
                self.assertEqual(response.json(), {'inventory': add_message})
                self.assertEqual(response.data['inventory'].code, 'invalid')
                response = self.client.post(f'/api/v1/pos/sales/orders/{order.pk}/submit/',
                            {}, format='json', HTTP_ACCEPT_LANGUAGE=language)
                self.assertEqual(response.status_code, 400, response.data)
                self.assertEqual(response.json(), {'inventory': dispatch_message})
                self.assertEqual(response.data['inventory'].code, 'invalid')
        self.assert_stock('1000')
        self.assertEqual(order.items.count(), 2)
        self.assertFalse(OrderConsumption.objects.exists())
        self.assertFalse(KitchenTicket.objects.filter(order=order).exists())
        item.refresh_from_db()
        self.assertEqual(item.status, OrderItem.Status.NEW)

    def test_cancellation_restores_original_quantity_and_cost_after_recipe_change(self):
        order, item = self.create_order(2)
        self.submit_order_via_api(order.pk)
        self.new_recipe('175')
        response = self.delete_item(item, 'not_prepared')
        self.assertIn(response.status_code, (200, 204), response.data)
        balance = self.assert_stock('1000')
        self.assertEqual(balance.value, Decimal('10000'))
        restored = StockMovement.objects.get(document__kind='sale_return')
        self.assertEqual(restored.quantity, 200)
        self.assertEqual(restored.unit_cost, 10)
        consumption = OrderConsumption.objects.get(order_item_id=item.pk)
        self.assertEqual(consumption.recipe_id, self.recipe.pk)
        self.assertEqual(consumption.resolved_quantity, 2)
        print_count = PrintDocument.objects.count()
        response = self.delete_item(item, 'not_prepared')
        # An independent request respects the closed-order guard. Network
        # retries reuse the Agent operation ID (covered by replay tests).
        self.assertEqual(response.status_code, 400, response.data)
        self.assert_stock('1000')
        self.assertEqual(StockMovement.objects.filter(document__kind='sale_return').count(), 1)
        self.assertEqual(PrintDocument.objects.count(), print_count)

    def test_prepared_waste_resolves_without_second_deduction_or_restore(self):
        order, item = self.create_order(2)
        self.submit_order_via_api(order.pk)
        response = self.delete_item(item, 'waste')
        self.assertIn(response.status_code, (200, 204), response.data)
        self.assert_stock('800')
        self.assertFalse(StockDocument.objects.filter(kind='sale_return').exists())
        self.assertEqual(ConsumptionResolution.objects.get().disposition, 'waste')
        self.assertEqual(OrderConsumption.objects.get(order_item_id=item.pk).resolved_quantity, 2)

    def test_partial_marking_return_transfers_remaining_historic_consumption(self):
        self.catalog_item.requires_marking = True
        self.catalog_item.marking_gtin = '04780012960214'
        self.catalog_item.save(update_fields=['requires_marking', 'marking_gtin', 'updated_at'])
        order, original = self.create_order(2)
        scanner = OrderMarkingScanService()
        codes = ['010478001296021421INVENTORY-FIRST', '010478001296021421INVENTORY-SECOND']
        for code in codes:
            scanner.scan(order=order, raw_code=code, scanned_by=self.user, mode='attach')
        self.submit_order_via_api(order.pk)
        self.new_recipe('300')
        response = self.client.post(
            f'/api/v1/pos/sales/orders/{order.pk}/scan-marking/',
            {'rawCode': codes[0], 'mode': 'remove', 'inventoryDisposition': 'returned'}, format='json',
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assert_stock('900')
        original.refresh_from_db()
        self.assertEqual(original.status, OrderItem.Status.CANCELLED)
        remaining = order.items.exclude(status=OrderItem.Status.CANCELLED).get()
        self.assertEqual(remaining.quantity, 1)
        self.assertEqual(remaining.markings.get().raw_code, codes[1])
        source = OrderConsumption.objects.get(order_item_id=original.pk)
        target = OrderConsumption.objects.get(order_item_id=remaining.pk)
        self.assertEqual(target.source_consumption_id, source.pk)
        self.assertEqual(target.recipe_id, self.recipe.pk)
        self.assertEqual(Decimal(target.components[0]['quantity']), 100)
        self.assertEqual(source.resolved_quantity, 2)
        self.submit_order_via_api(order.pk)
        self.assert_stock('900')
        response = self.delete_item(remaining, 'returned')
        self.assertIn(response.status_code, (200, 204), response.data)
        self.assert_stock('1000')
        self.assertEqual(StockDocument.objects.filter(kind='sale').count(), 1)

    def test_sale_trigger_consumes_only_fully_paid_order_once(self):
        self.new_recipe('100', trigger='sale')
        order, item = self.create_order(2)
        self.submit_order_via_api(order.pk)
        self.assert_stock('1000')
        shift = self.create_cash_shift()
        service = OrderPaymentService()
        with patch('apps.billing.services.order_payment.charge_payment', return_value={'ok': True, 'provider': 'test'}):
            first = service.process(
                order=order, payload={'method': Payment.Method.CASH, 'amount': 10000, 'register_fiscal': False},
                received_by=self.user, cash_shift=shift,
            )
            self.assertEqual(first['payment'].status, Payment.Status.SUCCEEDED)
            self.assert_stock('1000')
            self.assertFalse(OrderConsumption.objects.exists())
            service.process(
                order=order, payload={'method': Payment.Method.CASH, 'amount': 50000, 'register_fiscal': False},
                received_by=self.user, cash_shift=shift,
            )
        self.assert_stock('800')
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.CLOSED)
        OrderStateService().close_order_after_payment(order=order, received_by=self.user)
        self.assert_stock('800')
        self.assertEqual(OrderConsumption.objects.filter(order_item_id=item.pk).count(), 1)

    def test_no_station_consumed_item_cannot_change_quantity(self):
        self.catalog_item.prep_station = None
        self.catalog_item.save(update_fields=['prep_station', 'updated_at'])
        self.prep_station.is_active = False
        self.prep_station.save(update_fields=['is_active', 'updated_at'])
        order, item = self.create_order()
        self.assertIsNone(item.prep_station_id)
        submitted = self.submit_order_via_api(order.pk)
        self.assert_stock('900')
        self.assertTrue(submitted['items'][0]['inventory_consumed'])
        self.assertFalse(KitchenTicketLine.objects.filter(order_item=item).exists())
        response = self.client.patch(
            f'/api/v1/pos/sales/orders/items/{item.pk}/', {'quantity': 2}, format='json',
        )
        self.assertEqual(response.status_code, 400, response.data)
        item.refresh_from_db()
        self.assertEqual(item.quantity, 1)
        self.assert_stock('900')

    def test_selected_modifier_and_yield_affect_real_pos_consumption(self):
        group = ModifierGroup.objects.create(
            restaurant=self.restaurant, name='Qo‘shimcha', min_selections=0, max_selections=1,
        )
        option = ModifierOption.objects.create(group=group, name='Kartoshka+', price_delta=1000)
        CatalogItemModifierGroup.objects.create(catalog_item=self.catalog_item, modifier_group=group)
        self.new_recipe('100', yield_quantity='2', lines=[
            {'item': str(self.ingredient.pk), 'quantity': '100'},
            {'item': str(self.ingredient.pk), 'quantity': '25.5', 'modifier_option': str(option.pk)},
        ])
        order = self.create_order_via_api({'channel': 'takeaway', 'guest_count': 1})
        response = self.client.post(f'/api/v1/pos/sales/orders/{order["id"]}/items/', {
            'catalog_item': str(self.catalog_item.pk), 'quantity': 4,
            'selected_modifiers': [{'group': str(group.pk), 'options': [str(option.pk)]}],
        }, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        self.submit_order_via_api(order['id'])
        self.assert_stock('749')
        self.assertEqual(Decimal(OrderConsumption.objects.get().components[0]['quantity']), 251)

    def assert_cost_free(self, value):
        if isinstance(value, dict):
            for key, child in value.items():
                self.assertNotIn('cost', key.lower(), key)
                self.assertNotIn(key, {'value', 'valuationAdjustment', 'valuation_adjustment'})
                self.assert_cost_free(child)
        elif isinstance(value, list):
            for child in value:
                self.assert_cost_free(child)

    def test_public_menu_and_agent_snapshot_are_cost_free_and_preserve_manual_stoplist(self):
        order, _item = self.create_order(10)
        self.submit_order_via_api(order.pk)
        response = self.client.get('/api/v1/pos/catalog/menu/')
        self.assertEqual(response.status_code, 200, response.data)
        menu = response.json()
        item = next(item for category in menu for item in category['items'] if item['id'] == str(self.catalog_item.pk))
        self.assertTrue(item['inventory']['tracked'])
        self.assertTrue(item['inventory']['blocked'])
        self.assertEqual(Decimal(item['inventory']['availableQuantity']), 0)
        self.assert_cost_free(item['inventory'])
        agent_client, token = self.agent_client()
        response = agent_client.get('/api/v1/local-agent/sync/operational/', HTTP_AUTHORIZATION=f'Bearer {token}')
        self.assertEqual(response.status_code, 200, response.data)
        inventory = response.json()['inventory']
        self.assertEqual(inventory['version'], 1)
        self.assertEqual(inventory['warehouseId'], str(self.warehouse.pk))
        self.assertEqual(len(inventory['consumptions']), 1)
        self.assert_cost_free(inventory)
        self.catalog_item.is_stoplisted = True
        self.catalog_item.save(update_fields=['is_stoplisted', 'updated_at'])
        response = self.client.get('/api/v1/pos/catalog/menu/')
        self.assertFalse(any(
            item['id'] == str(self.catalog_item.pk)
            for category in response.json() for item in category['items']
        ))

    def test_agent_dispatch_replays_immutable_recipe_and_deduplicates(self):
        order, item = self.create_order(2)
        snapshots = self.replay_snapshot(item)
        self.new_recipe('300')
        client, token = self.agent_client()
        operation = {
            'operationId': 'inventory-dispatch-history', 'userId': str(self.user.pk),
            'method': 'POST', 'path': f'/api/v1/pos/sales/orders/{order.pk}/submit/',
            'body': {'edgeInventorySnapshots': snapshots},
        }
        for replayed in (False, True):
            response = client.post('/api/v1/local-agent/sync/mutations/', {'operations': [operation]},
                                   format='json', HTTP_AUTHORIZATION=f'Bearer {token}')
            self.assertEqual(response.status_code, 200, response.data)
            result = response.data['results'][0]
            self.assertEqual(result['status'], 200, result)
            self.assertEqual(result['replayed'], replayed)
        self.assert_stock('800')
        consumption = OrderConsumption.objects.get(order_item_id=item.pk)
        self.assertEqual(consumption.recipe_id, self.recipe.pk)
        self.assertEqual(StockDocument.objects.filter(kind='sale').count(), 1)

    def test_untrusted_pos_cannot_select_historic_recipe_snapshot(self):
        order, item = self.create_order()
        snapshots = self.replay_snapshot(item)
        current = self.new_recipe('300')
        response = self.client.post(f'/api/v1/pos/sales/orders/{order.pk}/submit/', {
            'edgeInventorySnapshots': snapshots,
        }, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assert_stock('700')
        self.assertEqual(OrderConsumption.objects.get(order_item_id=item.pk).recipe_id, current.pk)

    def test_agent_scanner_keeps_created_and_replacement_order_item_ids(self):
        self.catalog_item.requires_marking = True
        self.catalog_item.marking_gtin = '04780012960214'
        self.catalog_item.save(update_fields=['requires_marking', 'marking_gtin', 'updated_at'])
        order, original = self.create_order(2)
        codes = ['010478001296021421OFFLINE-1', '010478001296021421OFFLINE-2']
        scanner = OrderMarkingScanService()
        for code in codes:
            scanner.scan(order=order, raw_code=code, scanned_by=self.user, mode='attach')
        self.submit_order_via_api(order.pk)
        client, token = self.agent_client()
        replacement_id = uuid.uuid4()
        operation = {
            'operationId': 'inventory-scanner-remainder', 'userId': str(self.user.pk),
            'method': 'POST', 'path': f'/api/v1/pos/sales/orders/{order.pk}/scan-marking/',
            'body': {'rawCode': codes[0], 'mode': 'remove', 'inventoryDisposition': 'returned',
                     'edgeReplacementOrderItemId': str(replacement_id)},
        }
        for _ in range(2):
            response = client.post('/api/v1/local-agent/sync/mutations/', {'operations': [operation]},
                                   format='json', HTTP_AUTHORIZATION=f'Bearer {token}')
            self.assertEqual(response.data['results'][0]['status'], 200, response.data)
        self.assertTrue(OrderItem.objects.filter(pk=replacement_id, order=order).exists())
        self.assertTrue(OrderConsumption.objects.filter(order_item_id=replacement_id, source_consumption__order_item_id=original.pk).exists())
        self.assert_stock('900')
        created_id = uuid.uuid4()
        operation['operationId'] = 'inventory-scanner-created'
        operation['body'] = {'rawCode': '010478001296021421OFFLINE-3', 'mode': 'add',
                             'edgeCreatedOrderItemId': str(created_id)}
        response = client.post('/api/v1/local-agent/sync/mutations/', {'operations': [operation]},
                               format='json', HTTP_AUTHORIZATION=f'Bearer {token}')
        self.assertEqual(response.data['results'][0]['status'], 200, response.data)
        self.assertTrue(OrderItem.objects.filter(pk=created_id, order=order, quantity=1).exists())
