from rest_framework import status

from apps.integrations.models import IntegrationConfig
from apps.billing.models import Payment, Receipt
from apps.floor.models import TableSession
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

    def test_waiter_creates_an_immutable_precheck_document_for_the_receipt_printer(self):
        response = self.client.post(
            f"/api/v1/pos/billing/orders/{self.order['id']}/precheck/print-document/",
            {},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        document = PrintDocument.objects.get(id=response.data['printDocument'])
        self.assertEqual(document.kind, PrintTemplate.Kind.ORDER_PRECHECK)
        self.assertEqual(document.source_model, 'sales.order')
        self.assertEqual(str(document.source_id), self.order['id'])
        self.assertEqual(document.metadata['cashDeskId'], str(self.cash_desk.id))
        self.assertEqual(document.data_snapshot['order']['table'], self.table.name)
        self.assertEqual(document.data_snapshot['items'][0]['quantity'], 2)
        self.assertEqual(document.data_snapshot['totals']['total'], 66000)
        self.assertIn('printedAt', document.data_snapshot['precheck'])
        order = Order.objects.get(id=self.order['id'])
        self.table_session.refresh_from_db()
        self.assertEqual(order.status, Order.Status.OPEN)
        self.assertEqual(self.table_session.status, TableSession.Status.OPEN)
        self.assertFalse(Payment.objects.filter(order=order).exists())
        self.assertFalse(Receipt.objects.filter(order=order).exists())

    def test_closed_order_cannot_create_a_precheck_document(self):
        Order.objects.filter(id=self.order['id']).update(status=Order.Status.CLOSED)

        response = self.client.post(
            f"/api/v1/pos/billing/orders/{self.order['id']}/precheck/print-document/",
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
            f"/api/v1/pos/billing/orders/{self.order['id']}/precheck/print-document/",
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
