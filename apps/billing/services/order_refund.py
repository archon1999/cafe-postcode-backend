from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.billing.models import Payment, PaymentRefund, Receipt
from apps.sales.models import Order
from .financial_authority import FinancialAgentRequired
from .fiscal_evidence import fiscal_amount_minor, persist_fiscal_evidence


def refund_whole_order(*, payment, refunded_by, cash_shift, reason, edge_operation_id,
                       refund_result, fiscal_results, occurred_at, trusted_edge_replay,
                       manual_settlement_confirmed, refund_payments):
    """One immutable reversal of the original receipt, with separate tender ledger rows.

    Called inside PaymentRefundService's transaction. The order lock serializes
    requests arriving through different payment IDs on the same aggregate receipt.
    """
    if not trusted_edge_replay:
        raise FinancialAgentRequired()
    order = Order.objects.select_for_update().get(pk=payment.order_id)
    payments = list(Payment.objects.select_for_update().filter(order=order, status=Payment.Status.SUCCEEDED).order_by('id'))
    if order.status != Order.Status.CLOSED or payment.pk not in {p.pk for p in payments}:
        raise ValidationError({'detail': 'Only a fully paid closed order can be refunded.'})
    if cash_shift is None or cash_shift.cash_desk.restaurant_id != order.restaurant_id:
        raise ValidationError({'detail': 'A matching cashier shift is required.'})
    cash_shift = type(cash_shift).objects.select_for_update().get(pk=cash_shift.pk)
    if not edge_operation_id or not isinstance(refund_result, dict) or refund_result.get('ok') is not True:
        raise ValidationError({'detail': 'Confirmed refund identity and outcome are required.'})
    if (refund_result.get('edgeOperationId') or refund_result.get('edge_operation_id')) != edge_operation_id:
        raise ValidationError({'code': 'REFUND_IDENTITY_CONFLICT', 'detail': 'Refund operation mismatch.'})
    existing = list(PaymentRefund.objects.filter(payment__in=payments, status=PaymentRefund.Status.SUCCEEDED))
    if existing:
        if len(existing) == len(payments) and all(r.provider_payload.get('orderRefundOperationId') == edge_operation_id for r in existing):
            return {'refund': next(r for r in existing if r.payment_id == payment.pk),
                    'receipt': Receipt.objects.filter(order=order, kind=Receipt.Kind.REFUND).order_by('-created_at').first()}
        raise ValidationError({'code': 'REFUND_IDENTITY_CONFLICT', 'detail': 'This order already has a refund.'})
    total = sum(int(p.amount) for p in payments)
    if total != int(order.total):
        raise ValidationError({'detail': 'Full refund must match all original payments.'})
    if any(p.card_amount or p.method in {'card', 'mixed', 'qr'} for p in payments) and not manual_settlement_confirmed:
        raise ValidationError({'code': 'MANUAL_SETTLEMENT_REQUIRED', 'detail': 'Confirm the external card refund first.'})
    identities = {str(row.get('paymentOperationId')): row for row in refund_payments or []}
    if len(identities) != len(payments) or set(identities) != {str(p.edge_operation_id) for p in payments}:
        raise ValidationError({'detail': 'Original payment identities do not match the full refund.'})
    for p in payments:
        row = identities[str(p.edge_operation_id)]
        if int(row.get('amount', -1)) != int(p.amount) or not row.get('refundId'):
            raise ValidationError({'detail': 'Refund tender amounts do not match the original payments.'})
    originals = list(Receipt.objects.filter(order=order, kind=Receipt.Kind.FISCAL, status=Receipt.Status.SENT))
    results = fiscal_results or []
    if originals:
        if sum(fiscal_amount_minor(r.payload) for r in originals) != total * 100 or len(results) != len(originals):
            raise ValidationError({'detail': 'Full refund requires every original fiscal receipt.'})
        unmatched = {str(r.payload.get('response', {}).get('ReceiptSeq')): r for r in originals}
        for result in results:
            draft = result.get('request', {}).get('receipt', {})
            ref = draft.get('RefundInfo') or {}
            original = unmatched.pop(str(ref.get('ReceiptSeq')), None)
            if not original or result.get('ok') is not True or draft.get('Operation') != 1:
                raise ValidationError({'detail': 'Refund must reverse a distinct original fiscal receipt.'})
            source = original.payload.get('request', {}).get('receipt', {})
            proof = original.payload.get('response', {})
            source_date = str(proof.get('DateTime', '')).replace('-', '').replace(':', '').replace(' ', '').replace('T', '')[:14]
            if (not source.get('Items') or draft.get('Items') != source['Items']
                    or any(str(ref.get(k)) != str(proof.get(k)) for k in ('TerminalID', 'FiscalSign'))
                    or str(ref.get('DateTime')) != source_date
                    or fiscal_amount_minor(result) != fiscal_amount_minor(original.payload)):
                raise ValidationError({'detail': 'Refund items, tax and original receipt identity must remain exact.'})
        if sum(int(r['request']['receipt'].get('ReceivedCash', 0)) for r in results) != sum(p.cash_amount for p in payments) * 100:
            raise ValidationError({'detail': 'Refund cash allocation differs from original tenders.'})
        if sum(int(r['request']['receipt'].get('ReceivedCard', 0)) for r in results) != sum(p.card_amount for p in payments) * 100:
            raise ValidationError({'detail': 'Refund card allocation differs from original tenders.'})
    elif results or any(p.register_fiscal or (p.financial_snapshot or {}).get('fiscalRequested') for p in payments):
        raise ValidationError({'detail': 'Original fiscal receipt evidence is missing.'})
    now = occurred_at or timezone.now()
    records = []
    for p in payments:
        identity = identities[str(p.edge_operation_id)]
        records.append(PaymentRefund.objects.create(
            id=identity['refundId'], payment=p, amount=p.amount, cash_shift=cash_shift,
            status=PaymentRefund.Status.SUCCEEDED, reason=reason or '', refunded_by=refunded_by,
            refunded_at=now, edge_operation_id=edge_operation_id if p.pk == payment.pk else 'order-refund:' + str(identity['refundId']),
            provider_payload={**refund_result, 'orderRefundOperationId': edge_operation_id,
                              'manualSettlementConfirmed': manual_settlement_confirmed,
                              'confirmedBy': str(refunded_by.pk), 'amount': int(p.amount)},
        ))
    receipts = [persist_fiscal_evidence(payment=payment, result=r, kind=Receipt.Kind.REFUND, refund_total=total) for r in results]
    receipt = receipts[0] if receipts else Receipt.objects.create(order=order, payment=payment, kind=Receipt.Kind.REFUND, status=Receipt.Status.CREATED, payload={'fiscal_requested': False})
    from .cash_shift import CashShiftService
    CashShiftService().record_late_financial_projection(shift=cash_shift, operation_id=edge_operation_id, occurred_at=now)
    return {'refund': next(r for r in records if r.payment_id == payment.pk), 'receipt': receipt}
