import hashlib
import json

from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.billing.models import Receipt, FiscalReceiptAttempt
from apps.printing.services import attach_receipt_print_document
from .receipt_context import build_receipt_payload, parse_payload_datetime


def evidence_status(result):
    if result.get("ok") is True:
        return Receipt.Status.SENT
    outcome = str(
        result.get("outcome") or result.get("state") or result.get("fiscal_state") or ""
    ).lower()
    if result.get("definitive") is True or outcome in {
        "rejected",
        "rejected_final",
        "not_registered",
    }:
        return Receipt.Status.FAILED
    return Receipt.Status.UNKNOWN


def _hash(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def registration_key(result):
    if result.get("ok") is not True:
        return None
    response = result.get("response") or {}
    terminal = str(
        result.get("terminal_id")
        or response.get("TerminalID")
        or response.get("terminal_id")
        or ""
    )
    receipt_number = str(
        result.get("receipt_number")
        or response.get("ReceiptSeq")
        or response.get("receipt_seq")
        or ""
    )
    # Receipt sequence may reset between fiscal sessions. Provider's immutable
    # receipt datetime disambiguates legacy events without a fiscal-session ID.
    session = str(
        result.get("fiscal_session_id")
        or result.get("fiscalSessionId")
        or response.get("DateTime")
        or response.get("date_time")
        or ""
    )
    if not terminal or not receipt_number:
        raise ValidationError(
            {
                "edgeFiscalResults": "Successful fiscal evidence needs terminal and receipt identity."
            }
        )
    return _hash([result.get("provider"), terminal, session, receipt_number])


def fiscal_amount_minor(result):
    request = result.get("request") or {}
    receipt = request.get("receipt") or {}
    tenders = {
        str(key).lstrip("_").replace("_", "").lower(): value
        for key, value in receipt.items()
    }
    return int(tenders.get("receivedcash") or 0) + int(tenders.get("receivedcard") or 0)


def persist_fiscal_evidence(*, payment, result, receipt=None, kind=Receipt.Kind.FISCAL, refund_total=None):
    split_key = str(
        result.get("split_id")
        or result.get("splitId")
        or result.get("split_reason")
        or "default"
    )
    if len(split_key) > 128:
        raise ValidationError(
            {"edgeFiscalResults": "Fiscal split identity is too long."}
        )
    key = registration_key(result)
    if key:
        registered = Receipt.objects.filter(registration_key=key).first()
        if registered is not None:
            if registered.payment_id != payment.pk or registered.kind != kind:
                raise ValidationError(
                    {
                        "code": "FISCAL_IDENTITY_CONFLICT",
                        "detail": "This physical receipt belongs to another payment.",
                    }
                )
            receipt = registered
    receipt = (
        receipt
        or Receipt.objects.filter(
            payment=payment, kind=kind, split_key=split_key
        ).first()
    )
    outcome = evidence_status(result)
    if receipt is not None and receipt.status == Receipt.Status.SENT:
        existing_key = receipt.registration_key
        if key and not existing_key:
            existing_key = registration_key({**(receipt.payload or {}), 'ok': True})
        if key and existing_key != key:
            raise ValidationError(
                {
                    "code": "FISCAL_SPLIT_CONFLICT",
                    "detail": "A different physical receipt is already registered for this split.",
                }
            )
        if key and not receipt.registration_key:
            receipt.registration_key = key
            receipt.split_key = split_key
            receipt.save(update_fields=['registration_key', 'split_key', 'updated_at'])
        FiscalReceiptAttempt.objects.get_or_create(
            receipt=receipt, payload_hash=_hash(result), defaults={"payload": result}
        )
        return receipt  # Never downgrade or replace successful immutable evidence.
    if outcome == Receipt.Status.SENT:
        existing = Receipt.objects.filter(
            payment=payment, kind=kind, status=Receipt.Status.SENT
        )
        if receipt is not None:
            existing = existing.exclude(pk=receipt.pk)
        total = sum(
            fiscal_amount_minor(item.payload or {}) for item in existing
        ) + fiscal_amount_minor(result)
        expected = int(
            (payment.financial_snapshot or {}).get("orderTotal")
            or payment.order.total
            or payment.amount
        )
        if kind == Receipt.Kind.REFUND:
            expected = int(payment.amount if refund_total is None else refund_total)
        if total > expected * 100:
            raise ValidationError(
                {
                    "code": "FISCAL_TOTAL_CONFLICT",
                    "detail": "Combined physical receipts exceed the immutable sale amount.",
                }
            )
    values = dict(
        status=outcome,
        provider=str(result.get("provider") or ""),
        split_key=split_key,
        registration_key=key,
        fiscal_session_id=str(
            result.get("fiscal_session_id") or result.get("fiscalSessionId") or ""
        ),
        payload=build_receipt_payload(order=payment.order, receipt_result=result),
        fiscal_requested_at=parse_payload_datetime(result.get("fiscal_requested_at"))
        or timezone.now(),
        fiscal_registered_at=(
            parse_payload_datetime(
                result.get("fiscal_registered_at") or result.get("issued_at")
            )
            if outcome == Receipt.Status.SENT
            else None
        ),
        original_paid_at=payment.paid_at,
        fiscal_error_code=str(result.get("code") or result.get("error_code") or "")[
            :32
        ],
        fiscal_error_message=""
        if outcome == Receipt.Status.SENT
        else str(result.get("detail") or result.get("message") or ""),
    )
    if receipt is None:
        receipt = Receipt.objects.create(
            order=payment.order, payment=payment, kind=kind, **values
        )
    else:
        for field, value in values.items():
            setattr(receipt, field, value)
        receipt.save(update_fields=[*values, "updated_at"])
    FiscalReceiptAttempt.objects.get_or_create(
        receipt=receipt, payload_hash=_hash(result), defaults={"payload": result}
    )
    if outcome == Receipt.Status.SENT:
        attach_receipt_print_document(
            receipt=receipt, fiscal_result=result, created_by=payment.received_by
        )
    return receipt
