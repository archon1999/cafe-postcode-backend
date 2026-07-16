import logging

from django.utils import timezone

from apps.billing.helpers import get_receipt_model
from apps.printing.services import attach_receipt_print_document
from apps.sales.helpers import get_order_model

from .receipt_context import build_receipt_payload, parse_payload_datetime

logger = logging.getLogger(__name__)
Order = get_order_model()
Receipt = get_receipt_model()


class OrderPaymentCompletionMixin:
    def _complete_successful_payment(
        self, *, order, payment, received_by, fiscal_results=None
    ):
        if (
            order.channel == Order.Channel.TAKEAWAY
            and order.status == Order.Status.OPEN
        ):
            self.order_submission_service_class().submit(order)

        totals = self._succeeded_payment_totals(order=order)
        paid_total = int(totals.get("amount") or 0)
        is_fully_paid = paid_total >= int(order.total or 0)
        if is_fully_paid:
            self._apply_fiscal_breakdown(
                order=order,
                payment=payment,
                amount=paid_total,
                cash_amount=int(totals.get("cash_amount") or 0),
                card_amount=int(totals.get("card_amount") or 0),
            )
            self.state_service_class().close_order_after_payment(
                order=order, received_by=received_by
            )
        elif payment.register_fiscal:
            payment.register_fiscal = False
            payment.save(update_fields=["register_fiscal", "updated_at"])

        receipts = []
        if is_fully_paid and payment.register_fiscal:
            receipt_results = fiscal_results
            if receipt_results is None:
                receipt_results = self._issue_fiscal_receipts(
                    order=order, payment=payment, opened_by=received_by
                )
            for receipt_result in receipt_results or []:
                receipts.append(
                    self._create_fiscal_receipt(
                        order=order, payment=payment, receipt_result=receipt_result
                    )
                )
        if is_fully_paid and not payment.register_fiscal:
            receipts.append(
                self._create_plain_receipt(
                    order=order, payment=payment, created_by=received_by
                )
            )
        logger.info(
            "Payment processed",
            extra={
                "order_id": str(order.pk),
                "payment_id": str(payment.pk),
                "payment_status": payment.status,
                "receipt_count": len(receipts),
            },
        )
        return {
            "payment": payment,
            "receipt": receipts[0] if receipts else None,
            "receipts": receipts,
            "order": order,
        }

    def _issue_fiscal_receipts(self, *, order, payment, opened_by, split_reasons=None):
        from .order_payment import issue_fiscal_receipts

        try:
            self.shift_service_class().ensure_fiscal_shift_open(
                restaurant=order.restaurant,
                opened_by=opened_by,
            )
        except Exception as error:
            return self._fiscal_shift_open_error_results(
                error=error, split_reasons=split_reasons
            )
        return issue_fiscal_receipts(
            order=order, payment=payment, split_reasons=split_reasons
        )

    @staticmethod
    def _fiscal_shift_open_error_results(*, error, split_reasons=None):
        def payload(split_reason=""):
            result = {
                "ok": False,
                "provider": "",
                "code": "FISCAL_SHIFT_OPEN_FAILED",
                "detail": str(error),
                "fiscal_requested_at": timezone.now().isoformat(),
            }
            if split_reason:
                result["split_reason"] = split_reason
            return result

        if split_reasons:
            return [payload(str(split_reason or "")) for split_reason in split_reasons]
        return [payload()]

    @staticmethod
    def _should_submit_before_payment(*, order):
        return (
            order.status == Order.Status.OPEN
            and order.channel != Order.Channel.TAKEAWAY
        )

    def _create_fiscal_receipt(self, *, order, payment, receipt_result: dict):
        status = (
            Receipt.Status.SENT if receipt_result.get("ok") else Receipt.Status.FAILED
        )
        payload = build_receipt_payload(order=order, receipt_result=receipt_result)
        receipt = Receipt.objects.create(
            order=order,
            payment=payment,
            kind=Receipt.Kind.FISCAL,
            status=status,
            provider=receipt_result.get("provider", ""),
            payload=payload,
            fiscal_requested_at=parse_payload_datetime(
                receipt_result.get("fiscal_requested_at")
            )
            or timezone.now(),
            fiscal_registered_at=parse_payload_datetime(
                receipt_result.get("fiscal_registered_at")
            )
            if status == Receipt.Status.SENT
            else None,
            original_paid_at=payment.paid_at,
            fiscal_error_code=str(
                receipt_result.get("code") or receipt_result.get("error_code") or ""
            ),
            fiscal_error_message=""
            if status == Receipt.Status.SENT
            else str(
                receipt_result.get("detail") or receipt_result.get("message") or ""
            ),
        )
        if status == Receipt.Status.SENT:
            attach_receipt_print_document(
                receipt=receipt,
                fiscal_result=receipt_result,
                created_by=payment.received_by,
            )
        return receipt

    @staticmethod
    def _create_plain_receipt(*, order, payment, created_by):
        receipt = Receipt.objects.create(
            order=order,
            payment=payment,
            kind=Receipt.Kind.PLAIN,
            status=Receipt.Status.CREATED,
            provider="local-edge",
            payload={},
            original_paid_at=payment.paid_at,
        )
        attach_receipt_print_document(receipt=receipt, created_by=created_by)
        return receipt
