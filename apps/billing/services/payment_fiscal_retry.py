from django.db import transaction
from rest_framework.exceptions import ValidationError

from apps.billing.helpers import get_payment_model, get_receipt_model

from .fiscal_evidence import persist_fiscal_evidence

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
                {"detail": "Only successful payments can have fiscal results."}
            )
        existing = list(
            payment.receipts.filter(kind=Receipt.Kind.FISCAL).order_by("created_at")
        )
        if fiscal_results is None:
            if existing and all(
                receipt.status == Receipt.Status.SENT for receipt in existing
            ):
                return self._response(
                    payment, existing, [receipt.payload or {} for receipt in existing]
                )
            from .financial_authority import FinancialAgentRequired

            raise FinancialAgentRequired()
        if not fiscal_results:
            raise ValidationError(
                {"edgeFiscalResults": "Fiscal outcome evidence is required."}
            )

        # Match immutable split / physical identity, never array position or
        # the fact that a different receipt already fiscalized this payment.
        receipts = []
        for result in fiscal_results:
            split_key = str(
                result.get("split_id")
                or result.get("splitId")
                or result.get("split_reason")
                or "default"
            )
            legacy = [
                receipt
                for receipt in existing
                if not receipt.split_key
                and str((receipt.payload or {}).get("split_reason") or "default")
                == split_key
            ]
            if len(legacy) > 1:
                raise ValidationError(
                    {
                        "code": "FISCAL_SPLIT_AMBIGUOUS",
                        "detail": "Legacy receipts need explicit split reconciliation.",
                    }
                )
            receipt = persist_fiscal_evidence(
                payment=payment, result=result, receipt=legacy[0] if legacy else None
            )
            receipts.append(receipt)
        if not payment.register_fiscal:
            payment.register_fiscal = True
            payment.save(update_fields=["register_fiscal", "updated_at"])
        return self._response(payment, receipts, fiscal_results)

    @staticmethod
    def _response(payment, receipts, results):
        return {
            "payment": payment,
            "receipt": receipts[0] if receipts else None,
            "receipts": receipts,
            "result": results[0] if results else {},
            "results": results,
        }
