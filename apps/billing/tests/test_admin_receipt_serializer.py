from apps.billing.api.admin.serializers import (
    AdminReceiptSerializer,
    AdminReceiptWithPrintPreviewSerializer,
)
from apps.billing.models import Payment, Receipt
from apps.printing.services import attach_receipt_print_document
from apps.sales.api.admin.serializers import AdminOrderDetailSerializer
from apps.sales.models import Order
from apps.sales.tests.support.pos_api import PosTestCase


class AdminReceiptSerializerTests(PosTestCase):
    def test_includes_immutable_print_layout_and_data_snapshot(self):
        order = Order.objects.create(
            restaurant=self.restaurant,
            branch=self.branch,
            distribution_point=self.hall_distribution,
            opened_by=self.user,
            cashier=self.user,
            order_number=71,
            display_name="71",
            channel=Order.Channel.TAKEAWAY,
            status=Order.Status.CLOSED,
            subtotal=50000,
            total=50000,
        )
        payment = Payment.objects.create(
            order=order,
            received_by=self.user,
            method=Payment.Method.CASH,
            amount=order.total,
            status=Payment.Status.SUCCEEDED,
        )
        receipt = Receipt.objects.create(
            order=order,
            payment=payment,
            kind=Receipt.Kind.PLAIN,
            status=Receipt.Status.CREATED,
        )
        document = attach_receipt_print_document(receipt=receipt, created_by=self.user)
        receipt.refresh_from_db()

        data = AdminReceiptWithPrintPreviewSerializer(receipt).data

        self.assertEqual(data["print_document"], str(document.id))
        self.assertEqual(data["print_layout"], document.template_version.layout)
        self.assertEqual(data["print_data_snapshot"], document.data_snapshot)
        self.assertEqual(data["print_data_snapshot"]["order"]["displayNumber"], "71")

        order_detail = AdminOrderDetailSerializer(order).data
        self.assertEqual(
            order_detail["receipts"][0]["print_document"], str(document.id)
        )

        list_data = AdminReceiptSerializer(receipt).data
        self.assertNotIn("print_layout", list_data)
        self.assertNotIn("print_data_snapshot", list_data)

    def test_returns_null_print_preview_fields_for_legacy_receipt(self):
        order = Order.objects.create(
            restaurant=self.restaurant,
            branch=self.branch,
            distribution_point=self.hall_distribution,
            opened_by=self.user,
            cashier=self.user,
            order_number=72,
            display_name="72",
            channel=Order.Channel.TAKEAWAY,
            status=Order.Status.CLOSED,
        )
        receipt = Receipt.objects.create(
            order=order,
            kind=Receipt.Kind.PLAIN,
            status=Receipt.Status.CREATED,
        )

        data = AdminReceiptWithPrintPreviewSerializer(receipt).data

        self.assertIsNone(data["print_document"])
        self.assertIsNone(data["print_layout"])
        self.assertIsNone(data["print_data_snapshot"])
