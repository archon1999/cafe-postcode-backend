from django.db.models import Count, Exists, OuterRef, Q, Sum
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.billing.helpers import (
    get_payment_model,
    get_payment_refund_model,
    get_receipt_model,
)
from apps.billing.services.cash_shift_report import (
    build_unikassa_like_report,
    refund_tender_amounts,
    report_terminal_id,
)
from apps.printing.services import create_shift_report_print_document

Payment = get_payment_model()
PaymentRefund = get_payment_refund_model()
Receipt = get_receipt_model()


class CashShiftReportingMixin:
    def _payment_scope_queryset(
        self,
        *,
        shift=None,
        shifts=None,
        restaurant=None,
        cash_desk=None,
        paid_at_from=None,
        paid_at_to=None,
    ):
        payments = Payment.objects.filter(status=Payment.Status.SUCCEEDED)
        if shift is not None:
            payments = payments.filter(cash_shift=shift)
        if shifts is not None:
            payments = payments.filter(cash_shift__in=shifts)
        if restaurant is not None:
            payments = payments.filter(order__restaurant=restaurant)
        if cash_desk is not None:
            payments = payments.filter(cash_desk=cash_desk)
        if paid_at_from is not None:
            payments = payments.filter(paid_at__gte=paid_at_from)
        if paid_at_to is not None:
            payments = payments.filter(paid_at__lte=paid_at_to)
        return payments

    def get_unresolved_fiscal_payments_queryset(
        self,
        *,
        shift=None,
        shifts=None,
        restaurant=None,
        cash_desk=None,
        paid_at_from=None,
        paid_at_to=None,
    ):
        receipt_queryset = Receipt.objects.filter(
            payment_id=OuterRef("pk"), kind=Receipt.Kind.FISCAL
        )
        return (
            self._payment_scope_queryset(
                shift=shift,
                shifts=shifts,
                restaurant=restaurant,
                cash_desk=cash_desk,
                paid_at_from=paid_at_from,
                paid_at_to=paid_at_to,
            )
            .filter(register_fiscal=True)
            .annotate(
                has_fiscal_receipt=Exists(receipt_queryset),
                has_sent_fiscal_receipt=Exists(
                    receipt_queryset.filter(status=Receipt.Status.SENT)
                ),
                has_failed_fiscal_receipt=Exists(
                    receipt_queryset.filter(status=Receipt.Status.FAILED)
                ),
            )
            .filter(
                Q(has_fiscal_receipt=False)
                | Q(has_sent_fiscal_receipt=False)
                | Q(has_failed_fiscal_receipt=True)
            )
        )

    def ensure_no_unresolved_fiscal_payments(self, **filters):
        unresolved = self.get_unresolved_fiscal_payments_queryset(**filters)
        count = unresolved.count()
        if count:
            raise ValidationError(
                {
                    "detail": (
                        "Fiscalga yuborilmagan yoki xato bo‘lgan cheklar bor. "
                        'Smenani yopishdan oldin ularni "Yopilmagan hisoblar" bo‘limidan qayta yuboring.'
                    ),
                    "unresolved_fiscal_count": count,
                }
            )

    def build_fiscal_shift_report(
        self,
        *,
        shift=None,
        shifts=None,
        restaurant=None,
        cash_desk=None,
        paid_at_from=None,
        paid_at_to=None,
    ):
        payments = (
            self._payment_scope_queryset(
                shift=shift,
                shifts=shifts,
                restaurant=restaurant,
                cash_desk=cash_desk,
                paid_at_from=paid_at_from,
                paid_at_to=paid_at_to,
            )
            .select_related("order", "received_by")
            .prefetch_related("receipts")
            .order_by("paid_at", "created_at")
        )
        all_rows = []
        fiscal_rows = []
        for payment in payments:
            sent_receipts = [
                receipt
                for receipt in payment.receipts.all()
                if receipt.kind == Receipt.Kind.FISCAL
                and receipt.status == Receipt.Status.SENT
            ]
            row = {
                "payment_id": str(payment.id),
                "order_id": str(payment.order_id),
                "order_number": payment.order.order_number
                if payment.order_id
                else None,
                "method": payment.method,
                "amount": int(payment.amount or 0),
                "cash_amount": int(getattr(payment, "cash_amount", 0) or 0),
                "card_amount": int(getattr(payment, "card_amount", 0) or 0),
                "qr_amount": int(payment.amount or 0)
                if payment.method == Payment.Method.QR
                else 0,
                "paid_at": payment.paid_at.isoformat() if payment.paid_at else None,
                "cashier_name": payment.received_by.full_name
                if payment.received_by_id
                else "",
                "fiscal_receipt_count": len(sent_receipts),
            }
            all_rows.append(row)
            if sent_receipts:
                fiscal_rows.append(row)

        def summary(rows):
            totals = {}
            for row in rows:
                totals[row["method"]] = totals.get(row["method"], 0) + int(
                    row["amount"] or 0
                )
            return {
                "count": len(rows),
                "total": sum(totals.values()),
                "totals_by_method": totals,
                "rows": rows,
            }

        payment_ids = [payment.id for payment in payments]
        fiscal_payment_ids = [row["payment_id"] for row in fiscal_rows]
        refunds = list(
            PaymentRefund.objects.filter(
                payment_id__in=payment_ids, status=PaymentRefund.Status.SUCCEEDED
            )
            .select_related("payment")
            .order_by("refunded_at", "created_at")
        )
        fiscal_refunds = [
            refund
            for refund in refunds
            if str(refund.payment_id) in set(fiscal_payment_ids)
        ]
        terminal_id = report_terminal_id(cash_desk=cash_desk, payments=payments)
        opened_at = paid_at_from or (shift.opened_at if shift is not None else None)
        closed_at = paid_at_to or timezone.now()
        all_report = build_unikassa_like_report(
            source="pos",
            title="POS smena hisoboti",
            rows=all_rows,
            refunds=refunds,
            opened_at=opened_at,
            closed_at=closed_at,
            terminal_id=terminal_id,
            restaurant=restaurant
            or getattr(getattr(shift, "cash_desk", None), "restaurant", None),
        )
        fiscal_sent_report = build_unikassa_like_report(
            source="pos_fiscal_sent",
            title="Fiscalga yuborilgan POS hisoboti",
            rows=fiscal_rows,
            refunds=fiscal_refunds,
            opened_at=opened_at,
            closed_at=closed_at,
            terminal_id=terminal_id,
            restaurant=restaurant
            or getattr(getattr(shift, "cash_desk", None), "restaurant", None),
        )

        return {
            "all": summary(all_rows),
            "fiscal_sent": summary(fiscal_rows),
            "pos_report": all_report,
            "fiscal_sent_report": fiscal_sent_report,
        }

    def create_shift_report_documents(
        self, *, shift, created_by=None, closed=False, fiscal_report=None
    ):
        own_report = self.build_fiscal_shift_report(shift=shift)["pos_report"]
        documents = [
            create_shift_report_print_document(
                shift=shift,
                report=own_report,
                fiscal=False,
                closed=closed,
                created_by=created_by,
            )
        ]
        if fiscal_report is not None:
            documents.append(
                create_shift_report_print_document(
                    shift=shift,
                    report=fiscal_report,
                    fiscal=True,
                    closed=closed,
                    created_by=created_by,
                )
            )
        return documents

    def print_shift_reports(self, *, shift, created_by=None):
        fiscal_report = self.get_open_fiscal_report(shift=shift)
        return self.create_shift_report_documents(
            shift=shift,
            created_by=created_by,
            closed=False,
            fiscal_report=fiscal_report,
        )

    def get_open_fiscal_report(self, *, shift):
        if not self.has_open_fiscal_shift(restaurant=shift.cash_desk.restaurant):
            return None

        from . import cash_shift as cash_shift_module

        return cash_shift_module.get_fiscal_shift_report(
            restaurant=shift.cash_desk.restaurant,
            cash_desk=shift.cash_desk,
        )

    def build_shift_snapshot(self, *, shift):
        payments = shift.payments.filter(status=Payment.Status.SUCCEEDED)
        refunds = PaymentRefund.objects.filter(
            payment__cash_shift=shift, status=PaymentRefund.Status.SUCCEEDED
        )
        receipts = Receipt.objects.filter(payment__cash_shift=shift)

        totals = payments.aggregate(
            cash_total=Sum("cash_amount"),
            card_total=Sum("card_amount"),
            qr_total=Sum("amount", filter=Q(method=Payment.Method.QR)),
        )

        refund_total = refunds.aggregate(total=Sum("amount")).get("total") or 0
        cash_refund_total = sum(
            refund_tender_amounts(refund).get(Payment.Method.CASH, 0)
            for refund in refunds.select_related("payment")
        )

        return {
            "cash_total": totals.get("cash_total") or 0,
            "card_total": totals.get("card_total") or 0,
            "qr_total": totals.get("qr_total") or 0,
            "refund_total": refund_total,
            "receipt_count": receipts.filter(kind=Receipt.Kind.FISCAL)
            .aggregate(total=Count("id"))
            .get("total")
            or 0,
            "reprint_count": receipts.aggregate(total=Sum("reprint_count")).get("total")
            or 0,
            "expected_closing_cash_amount": (shift.opening_cash_amount or 0)
            + (totals.get("cash_total") or 0)
            - cash_refund_total,
        }
