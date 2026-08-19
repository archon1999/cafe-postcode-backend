from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from rest_framework.exceptions import ValidationError

from apps.billing.helpers import get_payment_model, get_receipt_model
from apps.printing.services import attach_receipt_print_document

from .receipt_context import build_receipt_payload, parse_payload_datetime

Payment = get_payment_model()
Receipt = get_receipt_model()


class PaymentFiscalRetryService:
    @transaction.atomic
    def retry(self, *, payment: Payment, fiscal_results=None):
        payment = (
            Payment.objects.select_for_update(of=("self",))
            .select_related("order", "order__restaurant", "received_by")
            .get(pk=payment.pk)
        )
        if payment.status != Payment.Status.SUCCEEDED:
            raise ValidationError(
                {
                    "detail": _(
                        "Only successful payments can be sent to fiscal integration."
                    )
                }
            )

        sent_receipts = list(
            payment.receipts.filter(
                kind=Receipt.Kind.FISCAL, status=Receipt.Status.SENT
            ).order_by("created_at")
        )
        pending_receipts = list(
            payment.receipts.filter(kind=Receipt.Kind.FISCAL)
            .exclude(status=Receipt.Status.SENT)
            .order_by("created_at")
        )
        if sent_receipts and not pending_receipts:
            for receipt in sent_receipts:
                if receipt.print_document_id is None:
                    attach_receipt_print_document(
                        receipt=receipt,
                        fiscal_result=receipt.payload or {},
                        created_by=payment.received_by,
                    )
            return {
                "payment": payment,
                "receipt": sent_receipts[0],
                "receipts": sent_receipts,
                "result": sent_receipts[0].payload or {},
                "results": [receipt.payload or {} for receipt in sent_receipts],
            }

        split_reasons = self._retry_split_reasons(
            sent_receipts=sent_receipts, pending_receipts=pending_receipts
        )
        receipts = []
        results = fiscal_results
        if results is None:
            from .order_payment import OrderPaymentService

            results = OrderPaymentService()._issue_fiscal_receipts(
                order=payment.order,
                payment=payment,
                opened_by=payment.received_by,
                split_reasons=split_reasons,
            )
        if not results or any(not result.get("ok") for result in results):
            return {
                "payment": payment,
                "receipt": None,
                "receipts": [],
                "result": results[0] if results else {},
                "results": results,
            }

        for index, receipt_result in enumerate(results):
            receipt = self._pick_existing_receipt(
                pending_receipts=pending_receipts,
                split_reason=str(receipt_result.get("split_reason") or ""),
                fallback_index=index,
            )
            receipts.append(
                self._persist_result(
                    payment=payment, receipt=receipt, receipt_result=receipt_result
                )
            )

        if not payment.register_fiscal:
            payment.register_fiscal = True
            payment.save(update_fields=["register_fiscal", "updated_at"])

        return {
            "payment": payment,
            "receipt": receipts[0] if receipts else None,
            "receipts": receipts,
            "result": results[0] if results else {},
            "results": results,
        }

    def _retry_split_reasons(
        self, *, sent_receipts: list[Receipt], pending_receipts: list[Receipt]
    ):
        if not sent_receipts:
            return None
        split_reasons = [
            str((receipt.payload or {}).get("split_reason") or "")
            for receipt in pending_receipts
            if str((receipt.payload or {}).get("split_reason") or "")
        ]
        if split_reasons:
            return list(dict.fromkeys(split_reasons))
        raise ValidationError(
            {
                "detail": _(
                    "This payment has partially registered fiscal receipts, but failed receipt split metadata is missing. "
                    "Retry is blocked to avoid duplicate fiscal registration."
                )
            }
        )

    def _pick_existing_receipt(
        self, *, pending_receipts: list[Receipt], split_reason: str, fallback_index: int
    ):
        for receipt in pending_receipts:
            payload = receipt.payload or {}
            if str(payload.get("split_reason") or "") == split_reason:
                pending_receipts.remove(receipt)
                return receipt
        if fallback_index < len(pending_receipts):
            return pending_receipts.pop(fallback_index)
        if pending_receipts:
            return pending_receipts.pop(0)
        return None

    def _persist_result(self, *, payment: Payment, receipt, receipt_result: dict):
        status = (
            Receipt.Status.SENT if receipt_result.get("ok") else Receipt.Status.FAILED
        )
        payload = build_receipt_payload(
            order=payment.order,
            receipt_result=receipt_result,
        )
        values = {
            "status": status,
            "provider": receipt_result.get("provider", ""),
            "payload": payload,
            "fiscal_requested_at": parse_payload_datetime(
                receipt_result.get("fiscal_requested_at")
            )
            or timezone.now(),
            "fiscal_registered_at": parse_payload_datetime(
                receipt_result.get("fiscal_registered_at")
            )
            if status == Receipt.Status.SENT
            else None,
            "original_paid_at": payment.paid_at,
            "fiscal_error_code": str(
                receipt_result.get("code") or receipt_result.get("error_code") or ""
            ),
            "fiscal_error_message": ""
            if status == Receipt.Status.SENT
            else str(
                receipt_result.get("detail") or receipt_result.get("message") or ""
            ),
        }
        if receipt is None:
            receipt = Receipt.objects.create(
                order=payment.order,
                payment=payment,
                kind=Receipt.Kind.FISCAL,
                **values,
            )
        else:
            for field, value in values.items():
                setattr(receipt, field, value)
            receipt.save(
                update_fields=[
                    "status",
                    "provider",
                    "payload",
                    "fiscal_requested_at",
                    "fiscal_registered_at",
                    "original_paid_at",
                    "fiscal_error_code",
                    "fiscal_error_message",
                    "updated_at",
                ]
            )
        if status == Receipt.Status.SENT:
            attach_receipt_print_document(
                receipt=receipt,
                fiscal_result=receipt_result,
                created_by=payment.received_by,
            )
        return receipt
