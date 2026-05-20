from rest_framework.exceptions import ValidationError

from apps.catalog.models import CatalogItem
from apps.sales.models import Order, OrderItem, OrderItemMarking
from apps.sales.services.marking import OrderMarkingScanService
from apps.sales.tests.support.pos_api import PosTestCase


class OrderMarkingScanServiceTests(PosTestCase):
    def setUp(self):
        super().setUp()
        self.service = OrderMarkingScanService()
        self.marked_item = CatalogItem.objects.create(
            restaurant=self.restaurant,
            category=self.category,
            name='Marked cola',
            prep_station=self.prep_station,
            price=12000,
            requires_marking=True,
            marking_gtin='04780012960214',
        )
        self.raw_code = '01047800129602142174jZF/l!h&hBm93lKpu'
        self.order = Order.objects.create(
            restaurant=self.restaurant,
            distribution_point=self.takeaway_distribution,
            opened_by=self.user,
            order_number=1001,
            channel=Order.Channel.TAKEAWAY,
            status=Order.Status.OPEN,
            guest_count=1,
        )

    def test_scan_add_creates_order_item_with_marking(self):
        self.service.scan(order=self.order, raw_code=self.raw_code, scanned_by=self.user, mode='add')

        order_item = OrderItem.objects.get(order=self.order, catalog_item=self.marked_item)
        marking = OrderItemMarking.objects.get(order_item=order_item)
        self.assertEqual(order_item.quantity, 1)
        self.assertEqual(marking.raw_code, self.raw_code)
        self.assertEqual(marking.gtin, '04780012960214')
        self.order.refresh_from_db()
        self.assertEqual(self.order.total, 12000)

    def test_scan_matches_tasnif_international_code_without_leading_zero(self):
        self.marked_item.marking_gtin = ''
        self.marked_item.mxik_payload = {'label': 1, 'internationalCode': '4780012960214'}
        self.marked_item.save(update_fields=['marking_gtin', 'mxik_payload', 'updated_at'])

        self.service.scan(order=self.order, raw_code=self.raw_code, scanned_by=self.user, mode='add')

        order_item = OrderItem.objects.get(order=self.order, catalog_item=self.marked_item)
        marking = OrderItemMarking.objects.get(order_item=order_item)
        self.assertEqual(marking.gtin, '04780012960214')
        self.assertEqual(order_item.quantity, 1)

    def test_scan_remove_deletes_matching_order_item(self):
        OrderItem.objects.create(
            order=self.order,
            catalog_item=self.marked_item,
            prep_station=self.prep_station,
            created_by=self.user,
            quantity=1,
            unit_price=12000,
            line_total=12000,
        )
        self.order.recalculate_totals()

        self.service.scan(order=self.order, raw_code=self.raw_code, scanned_by=self.user, mode='remove')

        self.assertFalse(OrderItem.objects.filter(order=self.order, catalog_item=self.marked_item).exists())
        self.order.refresh_from_db()
        self.assertEqual(self.order.total, 0)

    def test_scan_unknown_product_returns_validation_error(self):
        with self.assertRaises(ValidationError):
            self.service.scan(order=self.order, raw_code='019999999999999921ABC', scanned_by=self.user, mode='add')
