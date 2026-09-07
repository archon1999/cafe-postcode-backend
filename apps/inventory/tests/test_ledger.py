from decimal import Decimal
from datetime import timedelta

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Sum
from django.test import TestCase
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.catalog.models import CatalogItem, ModifierGroup, ModifierOption, CatalogItemModifierGroup
from apps.restaurants.models import Restaurant
from apps.sales.models import Order, OrderItem, OrderItemModifier
from apps.users.models import User
from apps.inventory import reports, services
from apps.inventory.models import (InventoryItem, OrderConsumption, Recipe, StockBalance,
                                   StockDocument, StockMovement, Supplier, Warehouse)


class InventoryLedgerTests(TestCase):
    def setUp(self):
        self.restaurant = Restaurant.objects.create(name='Inventory Cafe')
        self.other = Restaurant.objects.create(name='Other Cafe')
        self.user = User.objects.create_user('warehouse-admin', restaurant=self.restaurant, full_name='Omborchi')
        self.warehouse = services.default_warehouse(self.restaurant)
        self.supplier = Supplier.objects.create(restaurant=self.restaurant, name='Sabzavot')
        self.item = InventoryItem.objects.create(restaurant=self.restaurant, name='Kartoshka', base_unit='g',
                                                purchase_unit='kg', purchase_factor=1000, min_quantity=500)
        self.catalog = CatalogItem.objects.create(restaurant=self.restaurant, name='Qovurma', price=20000)
        self.order = Order.objects.create(restaurant=self.restaurant, order_number=1)

    def document(self, kind='receipt', quantity='10000', cost='8', post=True, **extra):
        data = {'kind': kind, 'warehouse': str(self.warehouse.pk), 'supplier': str(self.supplier.pk),
                'reference': 'TEST-1', 'responsible_name': 'Omborchi', 'reason': 'Test asos',
                'lines': [{'item': str(self.item.pk), 'quantity': quantity, 'unit_cost': cost}], **extra}
        document = services.create_document(self.restaurant, data, self.user)
        return services.post_document(document, self.user) if post else document

    def recipe(self, amount='100', **extra):
        return services.create_recipe(self.restaurant, {'catalog_item': str(self.catalog.pk),
                'lines': [{'item': str(self.item.pk), 'quantity': amount}], **extra}, self.user)

    def order_item(self, quantity='1'):
        return OrderItem.objects.create(order=self.order, catalog_item=self.catalog, quantity=Decimal(quantity), unit_price=20000)

    def balance(self):
        return StockBalance.objects.get(warehouse=self.warehouse, item=self.item)

    def assert_ledger_matches(self):
        total = StockMovement.objects.filter(warehouse=self.warehouse, item=self.item).aggregate(quantity=Sum('quantity'), value=Sum('value'))
        self.assertEqual(total['quantity'], self.balance().quantity)
        self.assertEqual(total['value'], self.balance().value)

    def test_receipt_conversion_weighted_average_and_issue(self):
        self.document(quantity='10', cost='8000', lines=[{'item': str(self.item.pk), 'quantity': '10', 'unit_cost': '8000', 'input_unit': 'purchase'}])
        self.document(quantity='10000', cost='12')
        self.assertEqual(self.balance().quantity, Decimal('20000'))
        self.assertEqual(self.balance().average_cost, Decimal('10'))
        issue = self.document(kind='issue', quantity='4000')
        self.assertEqual(issue.total_value, Decimal('-40000'))
        self.assertEqual(self.balance().value, Decimal('160000'))
        self.assert_ledger_matches()

    def test_purchase_unit_issue_keeps_cost_per_input_unit(self):
        self.document(quantity='10000', cost='8')
        issue = self.document(kind='issue', lines=[{'item': str(self.item.pk), 'quantity': '1', 'input_unit': 'purchase'}])
        self.assertEqual(issue.lines.get().unit_cost, Decimal('8000'))
        self.assertEqual(issue.total_value, Decimal('-8000'))

    def test_idempotent_create_post_and_conflicting_key(self):
        first = self.document(idempotency_key='receipt-test')
        second = self.document(idempotency_key='receipt-test')
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(StockMovement.objects.count(), 1)
        with self.assertRaises(ValidationError):
            self.document(quantity='2', idempotency_key='receipt-test')
        self.assertEqual(self.balance().quantity, Decimal('10000'))

    def test_post_failure_rolls_back_all_lines(self):
        other_item = InventoryItem.objects.create(restaurant=self.restaurant, name='Tuxum', base_unit='piece')
        self.document()
        doc = self.document(kind='issue', post=False, lines=[{'item': str(self.item.pk), 'quantity': '5'}, {'item': str(other_item.pk), 'quantity': '3'}])
        with self.assertRaises(ValidationError):
            services.post_document(doc, self.user)
        self.assertEqual(self.balance().quantity, Decimal('10000'))
        self.assertFalse(doc.movements.exists())

    def test_reversal_preserves_original_and_ledger(self):
        doc = self.document()
        original_movement = doc.movements.get()
        reversal = services.reverse_document(doc, 'Noto‘g‘ri kirim', self.user)
        self.assertEqual(services.reverse_document(doc, 'Noto‘g‘ri kirim', self.user).pk, reversal.pk)
        original_movement.refresh_from_db()
        self.assertEqual(original_movement.quantity, Decimal('10000'))
        self.assertEqual(self.balance().quantity, 0)
        self.assert_ledger_matches()
        with self.assertRaises(DjangoValidationError):
            original_movement.save()
        doc.refresh_from_db()
        with self.assertRaises(DjangoValidationError):
            doc.save()

    def test_receipt_and_return_require_document_metadata(self):
        doc = self.document(post=False, reference='')
        with self.assertRaises(ValidationError):
            services.post_document(doc)
        doc = self.document(post=False, supplier=None)
        with self.assertRaises(ValidationError):
            services.post_document(doc)

    def test_cross_tenant_references_rejected(self):
        foreign_item = InventoryItem.objects.create(restaurant=self.other, name='Secret', base_unit='g')
        with self.assertRaises(ValidationError):
            self.document(lines=[{'item': str(foreign_item.pk), 'quantity': '1'}])
        with self.assertRaises(ValidationError):
            self.document(warehouse=str(services.default_warehouse(self.other).pk))
        with self.assertRaises(ValidationError):
            self.recipe(lines=[{'item': str(foreign_item.pk), 'quantity': '1'}])

    def test_unknown_invalid_nonfinite_and_negative_amounts_rejected(self):
        for value in ['NaN', 'Infinity', '-1', '0', '1000000000000000000000']:
            with self.subTest(value=value), self.assertRaises(ValidationError):
                self.document(quantity=value)

    def test_opening_only_before_first_movement(self):
        self.document(kind='opening')
        with self.assertRaises(ValidationError):
            self.document(kind='opening')

    def test_immutable_recipe_and_idempotent_dispatch(self):
        self.document()
        first = self.recipe()
        row = self.order_item('2')
        services.consume_order_items(self.order, [row], self.user)
        self.recipe('200')
        services.consume_order_items(self.order, [row], self.user)
        self.assertEqual(self.balance().quantity, Decimal('9800'))
        consumption = OrderConsumption.objects.get(order_item_id=row.pk)
        self.assertEqual(consumption.recipe_id, first.pk)
        self.assertEqual(consumption.components[0]['quantity'], '200.000000')
        self.assert_ledger_matches()

    def test_modifier_and_yield_consumption(self):
        self.document()
        group = ModifierGroup.objects.create(restaurant=self.restaurant, name='Extra')
        modifier = ModifierOption.objects.create(group=group, name='Extra potato')
        CatalogItemModifierGroup.objects.create(catalog_item=self.catalog, modifier_group=group)
        self.recipe(yield_quantity='2', lines=[{'item': str(self.item.pk), 'quantity': '200'},
                    {'item': str(self.item.pk), 'quantity': '40', 'modifier_option': str(modifier.pk)}])
        row = self.order_item('3')
        OrderItemModifier.objects.create(order_item=row, modifier_option=modifier, group_name='Extra', option_name='Extra potato')
        services.consume_order_items(self.order, [row], self.user)
        self.assertEqual(self.balance().quantity, Decimal('9640'))

    def test_unlinked_modifier_rejected(self):
        group = ModifierGroup.objects.create(restaurant=self.restaurant, name='Other')
        modifier = ModifierOption.objects.create(group=group, name='Other modifier')
        with self.assertRaises(ValidationError):
            self.recipe(lines=[{'item': str(self.item.pk), 'quantity': '100', 'modifier_option': str(modifier.pk)}])

    def test_service_recipe_rejected(self):
        self.catalog.item_type = 'service'
        self.catalog.save()
        with self.assertRaises(ValidationError):
            self.recipe()

    def test_sale_trigger_is_separate_from_dispatch(self):
        self.document()
        self.recipe(trigger='sale')
        row = self.order_item()
        services.consume_order_items(self.order, [row], self.user)
        self.assertEqual(self.balance().quantity, Decimal('10000'))
        services.consume_order_items(self.order, [row], self.user, trigger='sale')
        self.assertEqual(self.balance().quantity, Decimal('9900'))

    def test_restore_original_cost_after_price_change_and_waste_no_double_outflow(self):
        self.document()
        self.recipe()
        row = self.order_item('2')
        services.consume_order_items(self.order, [row], self.user)
        self.document(cost='20')
        services.cancel_order_item(row, 'returned', self.user, quantity='1', event_key='return-1')
        returned = StockDocument.objects.get(kind='sale_return')
        self.assertEqual(returned.total_value, Decimal('800'))
        services.cancel_order_item(row, 'returned', self.user, quantity='1', event_key='return-1')
        before = self.balance().quantity
        services.cancel_order_item(row, 'waste', self.user, quantity='1', event_key='waste-1')
        self.assertEqual(self.balance().quantity, before)
        self.assert_ledger_matches()

    def test_partial_split_allocates_remainder_without_new_consumption(self):
        self.document()
        self.recipe()
        row = self.order_item('3')
        services.consume_order_items(self.order, [row], self.user)
        replacement = self.order_item('2')
        services.split_consumption(row, replacement, Decimal('1'), 'not_prepared', self.user)
        services.consume_order_items(self.order, [replacement], self.user)
        self.assertEqual(self.balance().quantity, Decimal('9800'))
        services.cancel_order_item(replacement, 'returned', self.user)
        self.assertEqual(self.balance().quantity, Decimal('10000'))
        services.cancel_order_item(row, 'returned', self.user)
        self.assertEqual(self.balance().quantity, Decimal('10000'))
        self.assert_ledger_matches()

    def test_stocktake_zero_valid_unrecorded_invalid_and_variance_preserved(self):
        self.document(quantity='70000')
        self.recipe('1000')
        row = self.order_item('40')
        services.consume_order_items(self.order, [row], self.user)
        self.document(kind='issue', quantity='1000')
        draft = self.document(kind='stocktake', quantity=None, post=False)
        with self.assertRaises(ValidationError):
            services.post_document(draft)
        draft = services.update_document(draft, {'lines': [{'item': str(self.item.pk), 'quantity': '27000'}]})
        services.post_document(draft, self.user)
        self.assertEqual(self.balance().quantity, Decimal('27000'))
        line = draft.lines.get()
        self.assertEqual(line.expected_quantity, Decimal('29000'))
        result = reports.variance(self.restaurant)[0]
        self.assertEqual(Decimal(result['variance_percent']), Decimal('5'))
        self.assertEqual(Decimal(result['variance_value']), Decimal('-16000'))
        self.assertFalse(result['requires_attention'])
        self.assert_ledger_matches()

    def test_stocktake_is_stale_after_any_movement_and_edit_does_not_reset_snapshot(self):
        self.document()
        draft = self.document(kind='stocktake', quantity=None, post=False)
        self.document(kind='issue', quantity='10')
        draft = services.update_document(draft, {'lines': [{'item': str(self.item.pk), 'quantity': '9980'}]})
        with self.assertRaises(ValidationError):
            services.post_document(draft)
        self.assertEqual(self.balance().quantity, Decimal('9990'))

    def test_stocktake_cannot_reverse_after_new_movements(self):
        self.document()
        count = self.document(kind='stocktake', quantity='9000')
        self.document(kind='issue', quantity='10')
        with self.assertRaises(ValidationError):
            services.reverse_document(count, 'Xato')

    def test_menu_availability_block_warn_and_manual_flag_preserved(self):
        self.recipe('100')
        self.item.availability_mode = 'block'
        self.item.save()
        self.catalog.is_stoplisted = True
        self.catalog.save()
        self.document(quantity='99')
        result = services.get_menu_inventory(self.catalog)
        self.assertTrue(result['blocked'])
        row = self.order_item()
        with self.assertRaises(ValidationError):
            services.consume_order_items(self.order, [row])
        self.item.availability_mode = 'warn'
        self.item.save()
        services.consume_order_items(self.order, [row])
        self.assertEqual(self.balance().quantity, Decimal('-1'))
        self.catalog.refresh_from_db()
        self.assertTrue(self.catalog.is_stoplisted)

    def test_negative_provisional_valuation_reconciliation_is_explicit_and_balanced(self):
        self.recipe('100')
        row = self.order_item()
        services.consume_order_items(self.order, [row])
        receipt = self.document(quantity='1000', cost='8')
        self.assertEqual(self.balance().average_cost, Decimal('8'))
        self.assertEqual(receipt.movements.get().valuation_adjustment, Decimal('-800'))
        self.assert_ledger_matches()

    def test_replay_uses_historical_verified_recipe_and_rejects_tampering(self):
        first = self.recipe('100')
        self.recipe('200')
        self.item.availability_mode = 'block'
        self.item.save()
        row = self.order_item()
        snapshot = {str(row.pk): {'orderItemId': str(row.pk), 'recipeId': str(first.pk),
                   'recipeVersion': first.version, 'quantity': '1',
                   'components': [{'itemId': str(self.item.pk), 'quantity': '100'}]}}
        with services.inventory_replay_context(self.restaurant, snapshot, timezone.now() - timedelta(minutes=5)):
            services.consume_order_items(self.order, [row])
        self.assertEqual(self.balance().quantity, Decimal('-100'))
        another = self.order_item()
        snapshot[str(row.pk)]['orderItemId'] = str(another.pk)
        snapshot[str(row.pk)]['components'][0]['quantity'] = '1'
        with self.assertRaises(ValidationError), services.inventory_replay_context(self.restaurant, snapshot):
            services.consume_order_items(self.order, [another])

    def test_bootstrap_has_no_costs_and_tracks_active_order_consumption(self):
        self.document()
        self.recipe()
        row = self.order_item()
        services.consume_order_items(self.order, [row])
        snapshot = services.inventory_snapshot(self.restaurant)
        self.assertEqual(snapshot['consumptions'][0]['order_item_id'], str(row.pk))
        self.assertNotIn('unit_cost', str(snapshot))
        self.assertNotIn('average_cost', str(snapshot))

    def test_kg_menu_and_actual_quantity_validation(self):
        self.catalog.sale_unit = 'kg'
        self.catalog.save()
        self.item.availability_mode = 'block'
        self.item.save()
        self.document(quantity='500')
        self.recipe('1000')
        self.assertFalse(services.get_menu_inventory(self.catalog)['blocked'])
        self.assertEqual(Decimal(services.get_menu_inventory(self.catalog)['available_quantity']), Decimal('0.5'))
        services.validate_catalog_stock(self.catalog, '0.5')
        with self.assertRaises(ValidationError):
            services.validate_catalog_stock(self.catalog, '0.501')
        self.item.availability_mode = 'warn'
        self.item.save()
        services.validate_catalog_stock(self.catalog, '100')

    def test_partial_returns_preserve_last_micro_unit(self):
        self.document(quantity='100')
        self.recipe(amount='1', yield_quantity='0.003')
        row = self.order_item('0.003')
        services.consume_order_items(self.order, [row])
        for index in range(3):
            services.cancel_order_item(row, 'returned', self.user, '0.001', f'part-{index}')
        self.assertEqual(self.balance().quantity, Decimal('100'))
        self.assert_ledger_matches()

    def test_replay_preserves_original_warehouse_after_default_change(self):
        self.document(quantity='1000')
        recipe = self.recipe()
        original = self.warehouse
        original.is_default = False
        original.save()
        current = Warehouse.objects.create(restaurant=self.restaurant, name='New default', is_default=True)
        row = self.order_item()
        snapshot = {str(row.pk): {'orderItemId': str(row.pk), 'recipeId': str(recipe.pk),
                    'recipeVersion': recipe.version, 'warehouseId': str(original.pk), 'quantity': '1',
                    'components': [{'itemId': str(self.item.pk), 'quantity': '100'}]}}
        with services.inventory_replay_context(self.restaurant, snapshot, timezone.now()):
            services.consume_order_items(self.order, [row])
        self.assertEqual(self.balance().quantity, Decimal('900'))
        self.assertFalse(StockBalance.objects.filter(warehouse=current).exists())

    def test_replay_after_count_is_visible_until_new_physical_count(self):
        self.document(quantity='1000')
        recipe = self.recipe()
        occurred = timezone.now() - timedelta(minutes=1)
        self.document(kind='stocktake', quantity='900')
        row = self.order_item()
        snapshot = {str(row.pk): {'orderItemId': str(row.pk), 'recipeId': str(recipe.pk),
                    'recipeVersion': recipe.version, 'quantity': '1',
                    'components': [{'itemId': str(self.item.pk), 'quantity': '100'}]}}
        with services.inventory_replay_context(self.restaurant, snapshot, occurred):
            services.consume_order_items(self.order, [row])
        self.assertTrue(any(value['id'].startswith('late:') for value in reports.insights(self.restaurant)['items']))
        self.document(kind='stocktake', quantity='900')
        self.assertFalse(any(value['id'].startswith('late:') for value in reports.insights(self.restaurant)['items']))
        self.assert_ledger_matches()

    def test_no_consumption_percent_is_null_not_invented(self):
        self.document()
        self.document(kind='stocktake', quantity='9000')
        row = reports.variance(self.restaurant)[0]
        self.assertIsNone(row['variance_percent'])
        self.assertTrue(row['requires_attention'])

    def test_price_and_cumulative_variance_recommendations_have_evidence(self):
        self.document()
        self.recipe()
        self.document(cost='12')
        self.document(kind='stocktake', quantity='19990')
        self.document(kind='stocktake', quantity='19980')
        insights = reports.insights(self.restaurant)['items']
        price = next(value for value in insights if value['id'].startswith('price:'))
        cumulative = next(value for value in insights if value['id'].startswith('monthly-variance:'))
        self.assertEqual(price['evidence']['cost_increase_percent'], '50.000000')
        self.assertEqual(len(price['evidence']['documents']), 2)
        self.assertEqual(Decimal(cumulative['evidence']['quantity']), Decimal('20'))
