from datetime import datetime, timedelta
from unittest.mock import patch

from django.utils import timezone
from djangorestframework_camel_case.util import camelize, underscoreize

from apps.billing.services.order_payment import OrderPaymentService, ServiceFeeQuoteStale
from apps.floor.models import TableSession
from apps.sales.models import Order, OrderItem
from apps.sales.serializers import OrderSerializer
from apps.sales.tests.support.pos_api import PosTestCase
from common.service_fee_formulas.catalog import normalize_definition
from common.service_fees import normalize_service_fee_snapshot
from common.service_fee_formulas import FormulaError
from rest_framework.test import APIClient
from apps.billing.api.pos.serializers.open_checks import OpenCheckOrderSerializer
from apps.printing.services.print_snapshots import build_order_precheck_print_snapshot


class FormulaServiceFeeTests(PosTestCase):
    def test_invalid_intermediate_item_edit_remains_correctable_and_blocks_payment(self):
        order = self.make_order('if(subtotal >= 90000, 1 / 0, subtotal / 10)')
        client = APIClient()
        client.force_authenticate(self.user)
        item_path = f'/api/v1/pos/sales/orders/{order.pk}/items/'
        response = client.post(item_path, {'catalog_item': str(self.catalog_item.pk), 'quantity': 2}, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        order.refresh_from_db()
        self.assertEqual(order.subtotal, 90000)
        # Even a previously supplied cashier total must not bypass the error.
        order.total_override = 1
        order.save(update_fields=['total_override'])
        for serializer in (OrderSerializer, OpenCheckOrderSerializer):
            data = serializer(order).data
            self.assertIsNone(data['total'])
            self.assertIsNone(data['service_fee_quote'])
            self.assertEqual(data['service_fee_error']['code'], 'SERVICE_FEE_FORMULA_ERROR')
        with self.assertRaises(FormulaError):
            OrderPaymentService._prepare_service_fee_quote(order=order, quote=None, trusted_edge_replay=False)
        with self.assertRaises(FormulaError):
            build_order_precheck_print_snapshot(order=order)
        response = client.patch(f"/api/v1/pos/sales/orders/items/{response.data['id']}/", {'quantity': '1'}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        order.refresh_from_db()
        self.assertEqual(order.subtotal, 60000)
        self.assertEqual(OrderSerializer(order).data['total'], 72000)
        self.assertIsNone(OrderSerializer(order).data['service_fee_error'])

    def make_order(self, source='duration_minutes * 1000', parameters=None, guests=3):
        self.table.service_fee_enabled = True
        self.table.service_fee_mode = 'formula'
        self.table.service_fee_formula = normalize_definition({'name': 'VIP', 'source': source, 'parameters': parameters or {}})
        self.table.save()
        self.start = timezone.now() - timedelta(minutes=90)
        session = TableSession.objects.create(restaurant=self.restaurant, hall=self.hall, table=self.table,
                                             opened_by=self.user, assigned_waiter=self.user, guest_count=guests, opened_at=self.start)
        order = Order.objects.create(restaurant=self.restaurant, table_session=session, distribution_point=self.hall_distribution,
                                     opened_by=self.user, channel=Order.Channel.HALL, order_number=900)
        OrderItem.objects.create(order=order, catalog_item=self.catalog_item, prep_station=self.prep_station,
                                 created_by=self.user, quantity=1, unit_price=30000)
        order.recalculate_totals(as_of=self.start + timedelta(minutes=90))
        return order

    def test_formula_adds_to_restaurant_percentage(self):
        order = self.make_order()
        self.assertEqual(order.get_service_fee_amount(as_of=self.start + timedelta(minutes=90)), 93000)
        self.assertEqual(order.calculated_total, 123000)
        self.assertEqual(order.service_fee_percent, 10)
        self.assertTrue(order.has_time_dependent_service_fee)

    def test_configuration_edits_do_not_reprice_open_order(self):
        order = self.make_order()
        self.table.service_fee_formula = normalize_definition({'source': 'duration_minutes * 9000'})
        self.table.save()
        order.refresh_from_db()
        self.assertEqual(order.get_service_fee_amount(as_of=self.start + timedelta(minutes=90)), 93000)

    def test_guest_count_is_frozen_in_session_snapshot(self):
        order = self.make_order('guest_count * 5000')
        order.table_session.guest_count = 10
        order.table_session.save()
        self.assertEqual(order.get_service_fee_amount(), 18000)
        self.assertFalse(order.has_time_dependent_service_fee)

    def test_frozen_formula_does_not_keep_growing(self):
        order = self.make_order()
        order.freeze_service_fee(at=self.start + timedelta(minutes=90))
        self.assertEqual(order.get_service_fee_amount(as_of=self.start + timedelta(hours=5)), 93000)

    def test_empty_session_snapshot_is_not_replaced_by_new_configuration(self):
        order = self.make_order()
        order.table_session.service_fee_snapshot = []
        order.table_session.save()
        order.capture_service_fee_snapshot()
        self.assertEqual(order.get_service_fee_amount(), 0)

    def test_recent_authoritative_quote_can_be_paid_without_per_second_race(self):
        order = self.make_order()
        quoted = self.start + timedelta(minutes=90)
        quote = {'quotedAt': quoted.isoformat(), 'billableMinutes': 90, 'serviceFee': 93000, 'calculatedTotal': 123000}
        with patch('apps.billing.services.order_payment.timezone.now', return_value=quoted + timedelta(seconds=5)):
            actual = OrderPaymentService._prepare_service_fee_quote(order=order, quote=quote, trusted_edge_replay=False)
        self.assertEqual(actual, quoted)
        for time_delta in (-1, 31):
            with patch('apps.billing.services.order_payment.timezone.now', return_value=quoted + timedelta(seconds=time_delta)):
                with self.assertRaises(ServiceFeeQuoteStale):
                    OrderPaymentService._prepare_service_fee_quote(order=order, quote=quote, trusted_edge_replay=False)

    def test_formula_parameter_identifiers_survive_wire_roundtrip(self):
        order = self.make_order('dayRate + day_rate', {'dayRate': '1000', 'day_rate': '2000'})
        from django.conf import settings
        options = settings.JSON_CAMEL_CASE['JSON_UNDERSCOREIZE']
        wire = camelize(OrderSerializer(order).data, **options)
        restored = underscoreize(wire, **options)
        formula = restored['service_fee_components'][1]['formula']
        self.assertEqual(formula['parameters'], {'dayRate': '1000', 'day_rate': '2000'})
        self.assertEqual(normalize_service_fee_snapshot(restored['service_fee_components'])[1]['formula'], formula)
