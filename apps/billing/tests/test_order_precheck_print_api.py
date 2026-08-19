from rest_framework import status

from apps.integrations.models import IntegrationConfig
from apps.billing.models import Payment, Receipt
from apps.floor.models import Hall, TableSession, ZoneOrCabin
from apps.printing.models import PrintDocument, PrintTemplate
from apps.sales.models import Order
from apps.sales.tests.support.pos_api import PosAPITestCase
from apps.users.models import Permission, PermissionEndpoint


class OrderPrecheckPrintApiTests(PosAPITestCase):
    def setUp(self):
        super().setUp()
        printer = IntegrationConfig.objects.create(
            restaurant=self.restaurant,
            name='Receipt printer',
            kind=IntegrationConfig.Kind.PRINTER,
            provider='escpos',
            settings={'connectionType': 'system_printer', 'printerName': 'POS-80'},
        )
        self.cash_desk.printer_integration = printer
        self.cash_desk.save(update_fields=('printer_integration', 'updated_at'))
        self.table_session = self.create_table_session()
        self.order = self.create_order_via_api(
            {'tableSession': str(self.table_session.id), 'channel': Order.Channel.HALL}
        )
        self.add_item_via_api(self.order['id'], quantity=2, note='Piyozsiz')

    def test_waiter_creates_an_immutable_precheck_document_for_the_receipt_printer(
        self,
    ):
        response = self.client.post(
            f'/api/v1/pos/billing/orders/{self.order["id"]}/precheck/print-document/',
            {},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        document = PrintDocument.objects.get(id=response.data['printDocument'])
        self.assertEqual(document.kind, PrintTemplate.Kind.ORDER_PRECHECK)
        self.assertEqual(
            document.template_version.template.kind,
            PrintTemplate.Kind.PAYMENT_RECEIPT_PLAIN,
        )
        self.assertEqual(document.source_model, 'sales.order')
        self.assertEqual(str(document.source_id), self.order['id'])
        self.assertLessEqual(
            len(document.idempotency_key),
            PrintDocument._meta.get_field('idempotency_key').max_length,
        )
        self.assertTrue(document.idempotency_key.startswith('order-precheck:'))
        self.assertEqual(document.metadata['cashDeskId'], str(self.cash_desk.id))
        self.assertEqual(document.data_snapshot['order']['table'], self.table.name)
        self.assertEqual(document.data_snapshot['order']['tableNumber'], self.table.table_number)
        self.assertEqual(document.data_snapshot['order']['zone'], self.zone.name)
        self.assertEqual(document.data_snapshot['order']['zoneDisplay'], '')
        self.assertEqual(document.data_snapshot['items'][0]['quantity'], 2)
        self.assertEqual(document.data_snapshot['totals']['total'], 66000)
        self.assertIn('printedAt', document.data_snapshot['precheck'])
        order = Order.objects.get(id=self.order['id'])
        self.table_session.refresh_from_db()
        self.assertEqual(order.status, Order.Status.OPEN)
        self.assertEqual(self.table_session.status, TableSession.Status.OPEN)
        self.assertFalse(Payment.objects.filter(order=order).exists())
        self.assertFalse(Receipt.objects.filter(order=order).exists())

    def test_precheck_includes_zone_display_when_restaurant_has_multiple_active_zones(
        self,
    ):
        second_zone = ZoneOrCabin.objects.create(
            restaurant=self.restaurant,
            name='VIP kabina',
            sort_order=2,
        )
        Hall.objects.create(zone_or_cabin=second_zone, name='VIP zal')

        response = self.client.post(
            f'/api/v1/pos/billing/orders/{self.order["id"]}/precheck/print-document/',
            {},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        document = PrintDocument.objects.get(id=response.data['printDocument'])
        self.assertEqual(document.data_snapshot['order']['zone'], self.zone.name)
        self.assertEqual(document.data_snapshot['order']['zoneDisplay'], self.zone.name)

    def test_precheck_renders_restaurant_hall_and_table_service_fees_separately(self):
        order = Order.objects.get(id=self.order['id'])
        order.hall_service_fee_percent = 3
        order.table_service_fee_percent = 2
        order.save(
            update_fields=[
                'hall_service_fee_percent',
                'table_service_fee_percent',
                'updated_at',
            ]
        )
        order.recalculate_totals()

        response = self.client.post(
            f'/api/v1/pos/billing/orders/{self.order["id"]}/precheck/print-document/',
            {},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        totals = PrintDocument.objects.get(id=response.data['printDocument']).data_snapshot['totals']
        self.assertEqual(totals['serviceFee'], 9000)
        self.assertEqual(totals['restaurantServiceFee'], 6000)
        self.assertEqual(totals['hallServiceFee'], 1800)
        self.assertEqual(totals['tableServiceFee'], 1200)
        self.assertEqual(totals['serviceFeePercent'], 15)

    def test_closed_order_cannot_create_a_precheck_document(self):
        Order.objects.filter(id=self.order['id']).update(status=Order.Status.CLOSED)

        response = self.client.post(
            f'/api/v1/pos/billing/orders/{self.order["id"]}/precheck/print-document/',
            {},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)
        self.assertFalse(PrintDocument.objects.filter(source_id=self.order['id']).exists())

    def test_cashier_can_print_precheck_without_table_or_takeaway_permissions(self):
        payment_permission = Permission.objects.get(code='pos_payments.create')
        PermissionEndpoint.objects.get_or_create(
            permission=payment_permission,
            method='POST',
            url='api/v1/pos/billing/orders/<uuid:pk>/precheck/print-document/',
        )
        self.role.permissions.set([payment_permission])

        response = self.client.post(
            f'/api/v1/pos/billing/orders/{self.order["id"]}/precheck/print-document/',
            {},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        order = Order.objects.get(id=self.order['id'])
        self.table_session.refresh_from_db()
        self.assertEqual(order.status, Order.Status.OPEN)
        self.assertEqual(self.table_session.status, TableSession.Status.OPEN)
        self.assertFalse(Payment.objects.filter(order=order).exists())
        self.assertFalse(Receipt.objects.filter(order=order).exists())
