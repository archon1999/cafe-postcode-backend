import hashlib
import json
import uuid

from django.db import transaction
from django.utils import timezone as timezone

from apps.printing.models import PrintDocument, PrintTemplate

from .print_snapshots import (
    _channel_label as _channel_label,
    _payment_method_label as _payment_method_label,
    build_kitchen_print_snapshot,
    build_order_precheck_print_snapshot,
    build_payment_print_snapshot,
)
from .receipt_payloads import build_legacy_receipt_payload
from .shift_report_snapshot import build_shift_report_print_snapshot
from .templates import ensure_restaurant_templates, ensure_shift_report_template


def _hash_document(*, snapshot: dict, template_version_id) -> str:
    canonical = json.dumps(
        {"snapshot": snapshot, "templateVersionId": str(template_version_id)},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@transaction.atomic
def create_shift_report_print_document(
    *, shift, report: dict, fiscal: bool, closed: bool, created_by=None
):
    template = ensure_shift_report_template(restaurant=shift.cash_desk.restaurant)
    snapshot = build_shift_report_print_snapshot(
        shift=shift, report=report, fiscal=fiscal, closed=closed
    )
    content_hash = _hash_document(
        snapshot=snapshot, template_version_id=template.published_version_id
    )
    mode = "fiscal" if fiscal else "general"
    idempotency_key = (
        f"shift-report:{shift.id}:close:{mode}"
        if closed
        else f"shift-report:{shift.id}:live:{mode}:{uuid.uuid4().hex}"
    )
    document, created = PrintDocument.objects.get_or_create(
        restaurant=shift.cash_desk.restaurant,
        idempotency_key=idempotency_key,
        defaults={
            "kind": PrintTemplate.Kind.SHIFT_REPORT,
            "operation_type": PrintDocument.OperationType.TEST,
            "source_model": "billing.cashshift",
            "source_id": shift.id,
            "data_snapshot": snapshot,
            "template_version": template.published_version,
            "content_hash": content_hash,
            "metadata": {
                "cashDeskId": str(shift.cash_desk_id),
                "reportType": mode,
                "closing": closed,
            },
            "created_by": created_by,
        },
    )
    if not created and document.content_hash != content_hash:
        raise ValueError(
            "Shift report print document already exists with different content."
        )
    return document


@transaction.atomic
def create_receipt_print_document(
    *, receipt, fiscal_result: dict | None = None, created_by=None
):
    kind_map = {
        "plain": PrintTemplate.Kind.PAYMENT_RECEIPT_PLAIN,
        "fiscal": PrintTemplate.Kind.PAYMENT_RECEIPT_FISCAL,
        "refund": (
            PrintTemplate.Kind.PAYMENT_RECEIPT_FISCAL
            if receipt.fiscal_registered_at
            else PrintTemplate.Kind.PAYMENT_RECEIPT_PLAIN
        ),
    }
    kind = kind_map[receipt.kind]
    ensure_restaurant_templates(restaurant=receipt.order.restaurant)
    template = PrintTemplate.objects.select_related("published_version").get(
        restaurant=receipt.order.restaurant,
        kind=kind,
    )
    snapshot = build_payment_print_snapshot(
        receipt=receipt, fiscal_result=fiscal_result
    )
    content_hash = _hash_document(
        snapshot=snapshot, template_version_id=template.published_version_id
    )
    document, created = PrintDocument.objects.get_or_create(
        restaurant=receipt.order.restaurant,
        idempotency_key=f"receipt:{receipt.id}",
        defaults={
            "kind": kind,
            "operation_type": (
                PrintDocument.OperationType.REFUND
                if receipt.kind == "refund"
                else PrintDocument.OperationType.SALE
            ),
            "source_model": "billing.receipt",
            "source_id": receipt.id,
            "data_snapshot": snapshot,
            "template_version": template.published_version,
            "content_hash": content_hash,
            "metadata": {
                "cashDeskId": (
                    str(receipt.payment.cash_desk_id)
                    if receipt.payment_id and receipt.payment.cash_desk_id
                    else None
                ),
            },
            "created_by": created_by,
        },
    )
    if not created and document.content_hash != content_hash:
        raise ValueError(
            "Print document idempotency key already exists with different content."
        )
    return document, snapshot


@transaction.atomic
def create_order_precheck_print_document(*, order, cash_desk=None, created_by=None):
    ensure_restaurant_templates(restaurant=order.restaurant)
    template = PrintTemplate.objects.select_related("published_version").get(
        restaurant=order.restaurant,
        kind=PrintTemplate.Kind.ORDER_PRECHECK,
    )
    snapshot = build_order_precheck_print_snapshot(order=order)
    content_hash = _hash_document(
        snapshot=snapshot, template_version_id=template.published_version_id
    )
    return PrintDocument.objects.create(
        restaurant=order.restaurant,
        kind=PrintTemplate.Kind.ORDER_PRECHECK,
        operation_type=PrintDocument.OperationType.SALE,
        idempotency_key=f"order-precheck:{order.id}:{uuid.uuid4().hex}",
        source_model="sales.order",
        source_id=order.id,
        data_snapshot=snapshot,
        template_version=template.published_version,
        content_hash=content_hash,
        metadata={"cashDeskId": str(cash_desk.id) if cash_desk else None},
        created_by=created_by,
    )


def attach_receipt_print_document(
    *, receipt, fiscal_result: dict | None = None, created_by=None
):
    """Create the immutable document once and persist its reference on the receipt."""
    if receipt.print_document_id:
        return receipt.print_document

    document, snapshot = create_receipt_print_document(
        receipt=receipt,
        fiscal_result=fiscal_result,
        created_by=created_by,
    )
    payload = dict(receipt.payload or {})
    if receipt.kind == "plain" and not payload:
        payload = build_legacy_receipt_payload(snapshot=snapshot)
    payload["print_document_id"] = str(document.id)
    receipt.print_document = document
    receipt.payload = payload
    receipt.save(update_fields=["print_document", "payload", "updated_at"])
    return document


@transaction.atomic
def create_kitchen_ticket_print_document(*, ticket, created_by=None):
    ticket = (
        type(ticket)
        .objects.select_for_update()
        .select_related("restaurant", "order", "prep_station")
        .get(pk=ticket.pk)
    )
    ensure_restaurant_templates(restaurant=ticket.restaurant)
    template = PrintTemplate.objects.select_related("published_version").get(
        restaurant=ticket.restaurant,
        kind=PrintTemplate.Kind.KITCHEN_TICKET,
    )
    snapshot = build_kitchen_print_snapshot(ticket=ticket)
    content_hash = _hash_document(
        snapshot=snapshot, template_version_id=template.published_version_id
    )
    existing = (
        PrintDocument.objects.filter(
            restaurant=ticket.restaurant,
            source_model="kitchen.kitchenticket",
            source_id=ticket.id,
            content_hash=content_hash,
        )
        .order_by("-created_at")
        .first()
    )
    if existing is not None:
        return existing, snapshot

    revision = (
        PrintDocument.objects.filter(
            restaurant=ticket.restaurant,
            source_model="kitchen.kitchenticket",
            source_id=ticket.id,
        ).count()
        + 1
    )
    document, created = PrintDocument.objects.get_or_create(
        restaurant=ticket.restaurant,
        idempotency_key=f"kitchen-ticket:{ticket.id}:v{revision}",
        defaults={
            "kind": PrintTemplate.Kind.KITCHEN_TICKET,
            "operation_type": PrintDocument.OperationType.SALE,
            "source_model": "kitchen.kitchenticket",
            "source_id": ticket.id,
            "data_snapshot": snapshot,
            "template_version": template.published_version,
            "content_hash": content_hash,
            "metadata": {
                "prepStationId": str(ticket.prep_station_id),
                "revision": revision,
            },
            "created_by": created_by,
        },
    )
    if not created and document.content_hash != content_hash:
        raise ValueError(
            "Kitchen print document idempotency key already exists with different content."
        )
    return document, snapshot
