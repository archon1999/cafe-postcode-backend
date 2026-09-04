from unittest.mock import patch

from django.utils import timezone
from rest_framework import status

from apps.billing.models import CashShift, FiscalShiftSession, Payment
from apps.sales.models import Order
from apps.sales.tests.support.pos_api import PosAPITestCase


class BackendShiftScenarioTests(PosAPITestCase):
    def test_single_desk_open_is_cashierless_and_duplicate_open_is_denied(self):
        first = self.open_shift_via_api(
            cash_desk_id=self.cash_desk.id, opening_cash_amount=100000
        )

        shift = CashShift.objects.get(pk=first["current_shift"]["id"])
        self.assertEqual(shift.opened_by_id, self.user.id)
        self.assertIsNone(shift.cashier_id)

        duplicate = self.client.post(
            "/api/v1/pos/billing/shifts/open/",
            {"cash_desk_id": str(self.cash_desk.id), "opening_cash_amount": 0},
            format="json",
        )

        self.assertEqual(duplicate.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("cashDeskId", duplicate.data)
        self.assertEqual(
            CashShift.objects.filter(
                cash_desk=self.cash_desk, status=CashShift.Status.OPEN
            ).count(),
            1,
        )

    def test_cash_close_freezes_mixed_tender_snapshot_and_creates_one_general_report(
        self,
    ):
        opened = self.open_shift_via_api(
            cash_desk_id=self.cash_desk.id, opening_cash_amount=100000
        )
        shift = CashShift.objects.get(pk=opened["current_shift"]["id"])
        order = self._closed_order(order_number=101, total=33000)
        Payment.objects.create(
            order=order,
            cash_shift=shift,
            cash_desk=self.cash_desk,
            received_by=self.user,
            method=Payment.Method.MIXED,
            amount=33000,
            cash_amount=20000,
            card_amount=13000,
            status=Payment.Status.SUCCEEDED,
            register_fiscal=False,
            paid_at=timezone.now(),
        )

        response = self.client.post(
            "/api/v1/pos/billing/shifts/current/close/",
            {"actual_closing_cash_amount": 118000, "close_fiscal_shift": False},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(len(response.data["printDocuments"]), 1)
        self.assertIsNone(response.data["current_shift"])
        shift.refresh_from_db()
        self.assertEqual(
            (
                shift.status,
                shift.cash_total,
                shift.card_total,
                shift.expected_closing_cash_amount,
                shift.actual_closing_cash_amount,
                shift.cash_difference_amount,
            ),
            (CashShift.Status.CLOSED, 20000, 13000, 120000, 118000, -2000),
        )
        self.assertEqual(shift.close_report_payload["report"]["all"]["count"], 1)

    def test_open_fiscal_session_still_prints_one_general_report_without_closing_shifts(self):
        opened = self.open_shift_via_api(
            cash_desk_id=self.cash_desk.id, opening_cash_amount=0
        )
        shift = CashShift.objects.get(pk=opened["current_shift"]["id"])
        fiscal_session = FiscalShiftSession.objects.create(
            restaurant=self.restaurant,
            opened_by=self.user,
            status=FiscalShiftSession.Status.OPEN,
            provider="fiscal-drive-service",
            terminal_id="TERM-1",
            opened_at=timezone.now(),
        )
        fiscal_report = {
            "TerminalID": "TERM-1",
            "OpenTime": "2026-07-15 08:00:00",
            "CloseTime": "",
            "TotalSaleCount": 0,
            "TotalRefundCount": 0,
            "TotalCash": {"Sale": 0, "Refund": 0},
            "TotalCard": {"Sale": 0, "Refund": 0},
            "TotalVAT": {"Sale": 0, "Refund": 0},
        }

        with patch(
            "apps.billing.services.cash_shift.get_fiscal_shift_report",
            return_value=fiscal_report,
        ) as get_fiscal_report:
            response = self.client.post(
                "/api/v1/pos/billing/shifts/current/print-report/",
                {"cash_shift_id": str(shift.id)},
                format="json",
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(len(response.data["printDocuments"]), 1)
        get_fiscal_report.assert_not_called()
        shift.refresh_from_db()
        fiscal_session.refresh_from_db()
        self.assertEqual(
            (shift.status, fiscal_session.status),
            (CashShift.Status.OPEN, FiscalShiftSession.Status.OPEN),
        )

    def test_unresolved_fiscal_payment_blocks_close_before_provider_and_preserves_both_shifts(
        self,
    ):
        opened = self.open_shift_via_api(
            cash_desk_id=self.cash_desk.id, opening_cash_amount=0
        )
        shift = CashShift.objects.get(pk=opened["current_shift"]["id"])
        fiscal_session = FiscalShiftSession.objects.create(
            restaurant=self.restaurant,
            opened_by=self.user,
            status=FiscalShiftSession.Status.OPEN,
            provider="unikassa",
            terminal_id="LG420",
            opened_at=timezone.now(),
        )
        order = self._closed_order(order_number=102, total=40000)
        Payment.objects.create(
            order=order,
            cash_shift=shift,
            cash_desk=self.cash_desk,
            received_by=self.user,
            method=Payment.Method.CASH,
            amount=40000,
            cash_amount=40000,
            status=Payment.Status.SUCCEEDED,
            register_fiscal=True,
            paid_at=timezone.now(),
        )

        with patch(
            "apps.billing.services.cash_shift.close_fiscal_shift"
        ) as close_provider:
            response = self.client.post(
                "/api/v1/pos/billing/shifts/current/close/",
                {"close_fiscal_shift": True},
                format="json",
            )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(int(response.data["unresolved_fiscal_count"]), 1)
        close_provider.assert_not_called()
        shift.refresh_from_db()
        fiscal_session.refresh_from_db()
        self.assertEqual(
            (shift.status, fiscal_session.status),
            (CashShift.Status.OPEN, FiscalShiftSession.Status.OPEN),
        )

    def _closed_order(self, *, order_number: int, total: int):
        return Order.objects.create(
            restaurant=self.restaurant,
            branch=self.branch,
            distribution_point=self.takeaway_distribution,
            opened_by=self.user,
            cashier=self.user,
            order_number=order_number,
            channel=Order.Channel.TAKEAWAY,
            status=Order.Status.CLOSED,
            guest_count=1,
            total=total,
            closed_at=timezone.now(),
        )
