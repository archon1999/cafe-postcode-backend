import hashlib
import json
import uuid

from django.db import transaction
from django.utils import timezone as timezone

from apps.printing.models import PrintDocument, PrintTemplate

from .print_snapshots import (
    _channel_label as _channel_label,
    _payment_method_label as _payment_method_label,
    build_kitchen_cancellation_print_snapshot,
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
        kind=PrintTemplate.Kind.PAYMENT_RECEIPT_PLAIN,
    )
    snapshot = build_order_precheck_print_snapshot(order=order)
    content_hash = _hash_document(
        snapshot=snapshot, template_version_id=template.published_version_id
    )
    return PrintDocument.objects.create(
        restaurant=order.restaurant,
        kind=PrintTemplate.Kind.ORDER_PRECHECK,
        operation_type=PrintDocument.OperationType.SALE,
        idempotency_key=f"order-precheck:{uuid.uuid4().hex}",
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
        .objects.select_for_update(of=("self",))
        .select_related(
            "restaurant",
            "order",
            "order__table_session__hall__zone_or_cabin",
            "order__table_session__table",
            "prep_station",
        )
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


@transaction.atomic
def create_kitchen_cancellation_print_document(
    *, ticket, order_item, quantity_delta, created_by=None
):
    ticket = (
        type(ticket)
        .objects.select_for_update(of=("self",))
        .select_related(
            "restaurant",
            "order",
            "order__table_session__hall__zone_or_cabin",
            "order__table_session__table",
            "prep_station",
        )
        .get(pk=ticket.pk)
    )
    order_item = (
        type(order_item)
        .objects.select_for_update(of=("self",))
        .select_related("catalog_item")
        .prefetch_related("modifiers")
        .get(pk=order_item.pk)
    )
    if (
        ticket.order_id != order_item.order_id
        or ticket.prep_station_id != order_item.prep_station_id
        or not ticket.lines.filter(order_item=order_item).exists()
    ):
        raise ValueError("Kitchen cancellation must reference the original dispatched ticket line.")

    idempotency_key = f"kitchen-cancellation:{order_item.id}"
    existing = (
        PrintDocument.objects.select_for_update()
        .filter(
            restaurant=ticket.restaurant,
            idempotency_key=idempotency_key,
        )
        .first()
    )
    if existing is not None:
        if (
            existing.kind != PrintTemplate.Kind.KITCHEN_TICKET
            or existing.operation_type != PrintDocument.OperationType.REFUND
            or existing.source_model != "sales.orderitem"
            or existing.source_id != order_item.id
            or existing.metadata.get("prepStationId") != str(ticket.prep_station_id)
        ):
            raise ValueError("Kitchen cancellation idempotency key has conflicting scope.")
        return existing, existing.data_snapshot

    ensure_restaurant_templates(restaurant=ticket.restaurant)
    template = PrintTemplate.objects.select_related("published_version").get(
        restaurant=ticket.restaurant,
        kind=PrintTemplate.Kind.KITCHEN_TICKET,
    )
    snapshot = build_kitchen_cancellation_print_snapshot(
        ticket=ticket,
        order_item=order_item,
        quantity_delta=quantity_delta,
    )
    content_hash = _hash_document(
        snapshot=snapshot,
        template_version_id=template.published_version_id,
    )
    document, created = PrintDocument.objects.get_or_create(
        restaurant=ticket.restaurant,
        idempotency_key=idempotency_key,
        defaults={
            "kind": PrintTemplate.Kind.KITCHEN_TICKET,
            "operation_type": PrintDocument.OperationType.REFUND,
            "source_model": "sales.orderitem",
            "source_id": order_item.id,
            "data_snapshot": snapshot,
            "template_version": template.published_version,
            "content_hash": content_hash,
            "metadata": {
                "prepStationId": str(ticket.prep_station_id),
                "orderId": str(ticket.order_id),
                "orderItemId": str(order_item.id),
                "originalKitchenTicketId": str(ticket.id),
                "originalDispatchNumber": ticket.dispatch_number,
                "kitchenOperation": "cancellation",
                "quantityDelta": snapshot["kitchen"]["quantityDelta"],
            },
            "created_by": created_by,
        },
    )
    if not created and document.content_hash != content_hash:
        raise ValueError(
            "Kitchen cancellation document already exists with different content."
        )
    return document, snapshot
