import json
import uuid
from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.utils import timezone

from apps.billing.models import Payment, Receipt
from apps.kitchen.models import KitchenTicket
from apps.printing.models import PrintTemplate
from apps.printing.services.documents import (
    build_kitchen_print_snapshot,
    build_payment_print_snapshot,
    build_shift_report_print_snapshot,
)
from apps.printing.services.templates import ensure_restaurant_templates
from apps.sales.models import Order, OrderItem
from apps.sales.tests.support.pos_api import PosTestCase


class BackendPrintingScenarioTests(PosTestCase):
    opened_at = datetime(2026, 7, 15, 9, 10, 11, tzinfo=ZoneInfo("Asia/Tashkent"))
    paid_at = datetime(2026, 7, 15, 10, 20, 30, tzinfo=ZoneInfo("Asia/Tashkent"))

    def setUp(self):
        super().setUp()
        self.restaurant.name = "Qamish Gamburg"
        self.restaurant.legal_name = "QAMISH GAMBURG MCHJ"
        self.restaurant.address = "Toshkent, Qamish ko'chasi 1"
        self.restaurant.phone = "+998 90 000 00 00"
        self.restaurant.social = "@qamish"
        self.restaurant.tax_number = "312217845"
        self.restaurant.vat_enabled = True
        self.restaurant.vat_percent = 12
        self.restaurant.save(
            update_fields=[
                "name",
                "legal_name",
                "address",
                "phone",
                "social",
                "tax_number",
                "vat_enabled",
                "vat_percent",
                "updated_at",
            ]
        )

    def test_precheck_and_fiscal_snapshots_preserve_content_and_layout_roles(self):
        order = self._order_with_two_identical_items()
        payment = Payment.objects.create(
            id=uuid.UUID("10000000-0000-0000-0000-000000000001"),
            order=order,
            cash_desk=self.cash_desk,
            received_by=self.user,
            method=Payment.Method.MIXED,
            amount=66000,
            cash_amount=40000,
            card_amount=26000,
            status=Payment.Status.SUCCEEDED,
            register_fiscal=True,
            paid_at=self.paid_at,
        )
        receipt = Receipt.objects.create(
            id=uuid.UUID("20000000-0000-0000-0000-000000000001"),
            order=order,
            payment=payment,
            kind=Receipt.Kind.FISCAL,
            status=Receipt.Status.SENT,
            fiscal_registered_at=self.paid_at,
        )
        fiscal_result = {
            "receipt_number": "704",
            "terminal_id": "TERM-QAMISH-1",
            "factory_id": "FM-QAMISH-1",
            "fiscal_sign": "SIGN-704",
            "qr_code_url": "https://ofd.soliq.uz/check?q=704",
        }

        snapshot = build_payment_print_snapshot(
            receipt=receipt,
            fiscal_result=fiscal_result,
        )

        self.assertEqual(
            snapshot,
            {
                "restaurant": {
                    "name": "Qamish Gamburg",
                    "legalName": "QAMISH GAMBURG MCHJ",
                    "address": "Toshkent, Qamish ko'chasi 1",
                    "phone": "+998 90 000 00 00",
                    "social": "@qamish",
                    "taxNumber": "312217845",
                },
                "order": {
                    "id": "30000000-0000-0000-0000-000000000001",
                    "displayNumber": "704",
                    "channel": "takeaway",
                    "channelLabel": "Soboy",
                    "table": "",
                    "hall": "",
                    "guestCount": 2,
                    "openedAt": "2026-07-15 09:10:11",
                    "waiter": "POS Test User",
                    "cashier": "POS Test User",
                    "note": "Achchiq sous alohida",
                    "deliveryPhone": "",
                    "deliveryAddress": "",
                },
                "items": [
                    {
                        "name": "Osh",
                        "quantity": 2,
                        "unitPrice": 30000,
                        "lineTotal": 60000,
                        "note": "Piyozsiz",
                        "modifierText": "",
                        "modifiers": [],
                        "vat": 6428,
                        "vatPercent": 12,
                    }
                ],
                "payment": {
                    "id": "10000000-0000-0000-0000-000000000001",
                    "method": "Aralash",
                    "amount": 66000,
                    "cash": 40000,
                    "card": 26000,
                    "change": 0,
                    "paidAt": "2026-07-15 10:20:30",
                    "operationType": "sale",
                },
                "totals": {
                    "subtotal": 60000,
                    "serviceFee": 6000,
                    "serviceFeePercent": 10,
                    "vat": 7071,
                    "vatPercent": 12,
                    "total": 66000,
                },
                "fiscal": {
                    "receiptNumber": "704",
                    "terminalId": "TERM-QAMISH-1",
                    "factoryId": "FM-QAMISH-1",
                    "fiscalSign": "SIGN-704",
                    "qrUrl": "https://ofd.soliq.uz/check?q=704",
                    "registeredAt": "2026-07-15 10:20:30",
                },
                "system": {"copyNumber": 1, "isReprint": False},
            },
        )

        templates = {
            template.kind: template
            for template in ensure_restaurant_templates(restaurant=self.restaurant)
        }
        plain_layout = json.dumps(
            templates[PrintTemplate.Kind.PAYMENT_RECEIPT_PLAIN]
            .published_version.layout,
            sort_keys=True,
        )
        fiscal_layout = json.dumps(
            templates[PrintTemplate.Kind.PAYMENT_RECEIPT_FISCAL]
            .published_version.layout,
            sort_keys=True,
        )
        self.assertNotIn("{{item.vat}}", plain_layout)
        self.assertNotIn("{{totals.vat}}", plain_layout)
        self.assertNotIn("{{fiscal.qrUrl}}", plain_layout)
        self.assertIn("{{item.vat}}", fiscal_layout)
        self.assertIn("{{totals.vat}}", fiscal_layout)
        self.assertIn("{{fiscal.qrUrl}}", fiscal_layout)

    def test_kitchen_snapshot_aggregates_duplicate_products_and_keeps_latin_channel(self):
        order = self._order_with_two_identical_items()
        ticket = KitchenTicket.objects.create(
            id=uuid.UUID("40000000-0000-0000-0000-00000000abc1"),
            restaurant=self.restaurant,
            order=order,
            prep_station=self.prep_station,
            routed_via=KitchenTicket.RouteMode.BOTH,
        )
        KitchenTicket.objects.filter(pk=ticket.pk).update(created_at=self.paid_at)
        ticket.refresh_from_db()

        snapshot = build_kitchen_print_snapshot(ticket=ticket)

        self.assertEqual(snapshot["restaurant"]["name"], "Qamish Gamburg")
        self.assertEqual(
            snapshot["order"],
            {
                "id": "30000000-0000-0000-0000-000000000001",
                "displayNumber": "704",
                "channel": "takeaway",
                "channelLabel": "Soboy",
                "table": "",
                "hall": "",
                "guestCount": 2,
                "openedAt": "2026-07-15 09:10:11",
                "waiter": "POS Test User",
                "cashier": "POS Test User",
                "note": "Achchiq sous alohida",
                "deliveryPhone": "",
                "deliveryAddress": "",
            },
        )
        self.assertEqual(
            snapshot["items"],
            [
                {
                    "name": "Osh",
                    "quantity": 2,
                    "unitPrice": 30000,
                    "lineTotal": 60000,
                    "note": "Piyozsiz",
                    "modifierText": "",
                    "modifiers": [],
                }
            ],
        )
        self.assertEqual(snapshot["totals"], {"total": 60000})
        self.assertEqual(
            snapshot["kitchen"],
            {
                "ticketNumber": "K-00ABC1",
                "prepStation": "Kitchen",
                "createdAt": "2026-07-15 10:20:30",
                "dispatchNumber": 1,
                "isAddition": False,
            },
        )

    def test_general_and_fiscal_shift_snapshots_preserve_money_scale(self):
        shift = self.create_cash_shift()
        type(shift).objects.filter(pk=shift.pk).update(opened_at=self.opened_at)
        shift.refresh_from_db()
        self.cash_desk.terminal_id = "KASSA-1"
        self.cash_desk.save(update_fields=["terminal_id", "updated_at"])
        report = {
            "TerminalID": "KASSA-1",
            "OpenTime": "2026-07-15 09:10:11",
            "CloseTime": "2026-07-15 18:00:00",
            "TotalSaleCount": 3,
            "TotalRefundCount": 1,
            "TotalCash": {"Sale": 50000, "Refund": 10000},
            "TotalCard": {"Sale": 30000, "Refund": 5000},
            "TotalQR": {"Sale": 10000, "Refund": 0},
            "TotalVAT": {"Sale": 9055, "Refund": 1607},
            "TotalSaleAmount": 90000,
            "TotalRefundAmount": 15000,
            "Payments": [{"order_number": 701}, {"order_number": 704}],
            "FactoryID": "FM-1",
            "SerialNumber": "SN-1",
            "FirstReceiptSeq": 21,
            "LastReceiptSeq": 23,
        }

        with patch(
            "apps.printing.services.documents.timezone.now",
            return_value=self.paid_at,
        ):
            general = build_shift_report_print_snapshot(
                shift=shift,
                report=report,
                fiscal=False,
                closed=True,
            )
            fiscal = build_shift_report_print_snapshot(
                shift=shift,
                report=report,
                fiscal=True,
                closed=True,
            )

        self.assertEqual(
            general["report"],
            {
                "label": "Umumiy hisobot",
                "terminalId": "KASSA-1",
                "factoryId": "FM-1",
                "serialNumber": "SN-1",
                "printedAt": "2026-07-15 10:20:30",
                "openedAt": "2026-07-15 09:10:11",
                "closedAt": "2026-07-15 18:00:00",
                "firstReceipt": "21",
                "lastReceipt": "23",
                "saleCount": 3,
                "refundCount": 1,
                "cashSale": 50000,
                "cardSale": 30000,
                "qrSale": 10000,
                "vatSale": 0,
                "totalSale": 90000,
                "cashRefund": 10000,
                "cardRefund": 5000,
                "qrRefund": 0,
                "vatRefund": 0,
                "totalRefund": 15000,
                "expenseTotal": 0,
                "netCashAfterExpenses": 40000,
            },
        )
        self.assertEqual(
            fiscal["report"],
            {
                **general["report"],
                "label": "Fiscal to'lovlar",
                "cashSale": 500,
                "cardSale": 300,
                "qrSale": 100,
                "vatSale": 90.55,
                "totalSale": 900,
                "cashRefund": 100,
                "cardRefund": 50,
                "vatRefund": 16.07,
                "totalRefund": 150,
                "netCashAfterExpenses": 400,
            },
        )
        self.assertEqual(general["system"], {"isFiscal": False, "isClosing": True})
        self.assertEqual(fiscal["system"], {"isFiscal": True, "isClosing": True})

    def _order_with_two_identical_items(self):
        order = Order.objects.create(
            id=uuid.UUID("30000000-0000-0000-0000-000000000001"),
            restaurant=self.restaurant,
            distribution_point=self.takeaway_distribution,
            opened_by=self.user,
            cashier=self.user,
            order_number=704,
            channel=Order.Channel.TAKEAWAY,
            status=Order.Status.SUBMITTED,
            guest_count=2,
            note="Achchiq sous alohida",
        )
        Order.objects.filter(pk=order.pk).update(created_at=self.opened_at)
        for _ in range(2):
            OrderItem.objects.create(
                order=order,
                catalog_item=self.catalog_item,
                prep_station=self.prep_station,
                created_by=self.user,
                quantity=1,
                unit_price=30000,
                note="Piyozsiz",
            )
        order.recalculate_totals()
        order.refresh_from_db()
        return order
