from decimal import Decimal, ROUND_HALF_UP

from django.db.models import Sum
from django.utils import timezone

from apps.floor.services import restaurant_has_multiple_active_zones, table_session_zone_name


def _money(value) -> int:
    return int(value or 0)


def _json_number(value) -> int | float:
    number = Decimal(str(value or 0))
    return int(number) if number == number.to_integral_value() else float(number)


def _included_vat(*, amount: int, percent) -> int:
    rate = Decimal(str(percent or 0))
    if amount <= 0 or rate <= 0:
        return 0
    value = Decimal(amount) * rate / (Decimal("100") + rate)
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _service_fee_totals(order) -> dict:
    components = order.get_service_fee_components()
    by_scope = {component["scope"]: component for component in components}

    def value(scope: str, field: str, default=0):
        return by_scope.get(scope, {}).get(field, default)

    return {
        "serviceFeePercent": _json_number(order.service_fee_percent),
        "serviceFeeComponents": [
            {
                **component,
                "percent": _json_number(component["percent"]),
            }
            for component in components
        ],
        "restaurantServiceFee": value("restaurant", "amount"),
        "restaurantServiceFeePercent": _json_number(value("restaurant", "percent")),
        "hallServiceFee": value("hall", "amount"),
        "hallServiceFeePercent": _json_number(value("hall", "percent")),
        "tableServiceFee": value("table", "amount"),
        "tableServiceFeePercent": _json_number(value("table", "percent")),
    }


def _channel_label(order) -> str:
    labels = {
        "hall": "Zal",
        "takeaway": "Soboy",
        "delivery": "Dostavka",
        "online": "Online",
    }
    return labels.get(str(order.channel or ""), str(order.channel or ""))


def _table_parts(order) -> tuple[str, int | None, str, str, str]:
    session = getattr(order, "table_session", None)
    table = getattr(session, "table", None) if session is not None else None
    hall = getattr(session, "hall", None) if session is not None else None
    zone_name = table_session_zone_name(session)
    zone_display = (
        zone_name
        if restaurant_has_multiple_active_zones(getattr(order, "restaurant_id", None))
        else ""
    )
    return (
        str(getattr(table, "name", "") or ""),
        getattr(table, "table_number", None),
        str(getattr(hall, "name", "") or ""),
        zone_name,
        zone_display,
    )


def _payment_method(*, cash_amount: int, card_amount: int, fallback: str) -> str:
    if cash_amount > 0 and card_amount > 0:
        return "mixed"
    if card_amount > 0:
        return "card"
    if cash_amount > 0:
        return "cash"
    return fallback


def _payment_method_label(value: str) -> str:
    return {
        "cash": "Naqd",
        "card": "Karta",
        "mixed": "Aralash",
        "qr": "QR",
    }.get(str(value or ""), str(value or ""))


def _local_datetime(value) -> str:
    if not value:
        return ""
    return timezone.localtime(value).strftime("%Y-%m-%d %H:%M:%S")


def _print_item_values(item) -> tuple[dict, tuple, str]:
    name = item.catalog_item.name if item.catalog_item_id else item.name_snapshot
    unit_price = _money(item.unit_price)
    modifier_rows = list(item.modifiers.all())
    modifier_signature = tuple(
        (str(row.modifier_option_id or ""), row.group_name, row.option_name, _money(row.price_delta))
        for row in modifier_rows
    )
    modifier_text = "\n".join(f"{row.group_name}: {row.option_name}" for row in modifier_rows)
    item_note = item.note or ""
    return (
        {
            "name": name,
            "unitPrice": unit_price,
            "note": item_note,
            "modifierText": modifier_text,
            "modifiers": [
                {
                    "groupName": row.group_name,
                    "optionName": row.option_name,
                    "priceDelta": _money(row.price_delta),
                }
                for row in modifier_rows
            ],
        },
        modifier_signature,
        item_note,
    )


def _aggregate_print_items(
    queryset, *, vat_enabled=False, vat_percent=0, include_vat=False
) -> list[dict]:
    aggregated = {}
    for item in queryset.order_by("created_at"):
        values, modifier_signature, item_note = _print_item_values(item)
        key = (
            str(item.catalog_item_id or values["name"]),
            modifier_signature,
            item_note,
            values["unitPrice"],
        )
        current = aggregated.setdefault(
            key,
            {**values, "quantity": 0, "lineTotal": 0},
        )
        current["quantity"] = _json_number(
            Decimal(str(current["quantity"])) + Decimal(item.quantity or 0)
        )
        current["lineTotal"] += _money(item.line_total)
        if include_vat:
            current["vat"] = current.get("vat", 0) + (
                _included_vat(amount=_money(item.line_total), percent=vat_percent)
                if vat_enabled
                else 0
            )
            current["vatPercent"] = _json_number(vat_percent)
    return list(aggregated.values())


def build_payment_print_snapshot(*, receipt, fiscal_result: dict | None = None) -> dict:
    order = receipt.order
    payment = receipt.payment
    restaurant = order.restaurant
    table_name, table_number, hall_name, zone_name, zone_display = _table_parts(order)
    active_items = order.items.exclude(
        status=order.items.model.Status.CANCELLED
    ).select_related("catalog_item").prefetch_related("modifiers")
    paid = order.payments.filter(status=payment.Status.SUCCEEDED).aggregate(
        amount=Sum("amount"),
        cash=Sum("cash_amount"),
        card=Sum("card_amount"),
    )
    amount = _money(paid.get("amount"))
    cash_amount = _money(paid.get("cash"))
    card_amount = _money(paid.get("card"))
    total = _money(order.total)
    subtotal = _money(order.subtotal)
    calculated_total = _money(order.calculated_total)
    vat_enabled = bool(getattr(restaurant, "vat_enabled", False))
    vat_percent = getattr(restaurant, "vat_percent", 0) or 0
    result = dict(fiscal_result or receipt.payload or {})
    response = (
        result.get("response") if isinstance(result.get("response"), dict) else {}
    )
    items = _aggregate_print_items(
        active_items,
        vat_enabled=vat_enabled,
        vat_percent=vat_percent,
        include_vat=True,
    )

    return {
        "restaurant": {
            "name": restaurant.name,
            "legalName": restaurant.legal_name or restaurant.name,
            "address": restaurant.address,
            "phone": restaurant.phone,
            "social": getattr(restaurant, "social", ""),
            "taxNumber": restaurant.tax_number,
        },
        "order": {
            "id": str(order.id),
            "displayNumber": str(order.display_name or order.order_number),
            "channel": order.channel,
            "channelLabel": _channel_label(order),
            "table": table_name,
            "tableNumber": table_number,
            "hall": hall_name,
            "zone": zone_name,
            "zoneDisplay": zone_display,
            "guestCount": int(order.guest_count or 0),
            "openedAt": _local_datetime(order.created_at),
            "waiter": order.opened_by.full_name
            if order.opened_by_id and order.opened_by
            else "",
            "cashier": order.cashier.full_name
            if order.cashier_id and order.cashier
            else "",
            "note": order.note or "",
            "deliveryPhone": order.delivery_phone or "",
            "deliveryAddress": order.delivery_address or "",
        },
        "items": items,
        "payment": {
            "id": str(payment.id),
            "method": _payment_method_label(
                _payment_method(
                    cash_amount=cash_amount,
                    card_amount=card_amount,
                    fallback=payment.method,
                )
            ),
            "amount": amount,
            "cash": cash_amount,
            "card": card_amount,
            "change": 0,
            "paidAt": _local_datetime(payment.paid_at),
            "operationType": "sale",
        },
        "totals": {
            "subtotal": subtotal,
            "serviceFee": max(calculated_total - subtotal, 0),
            **_service_fee_totals(order),
            **(
                {
                    "calculatedTotal": calculated_total,
                    "totalAdjustment": total - calculated_total,
                }
                if total != calculated_total
                else {}
            ),
            "vat": _included_vat(amount=total, percent=vat_percent)
            if vat_enabled
            else 0,
            "vatPercent": _json_number(vat_percent),
            "total": total,
        },
        "fiscal": {
            "receiptNumber": str(
                result.get("receipt_number")
                or result.get("receiptNumber")
                or response.get("ReceiptNumber")
                or ""
            ),
            "terminalId": str(
                result.get("terminal_id")
                or result.get("terminalId")
                or response.get("TerminalID")
                or ""
            ),
            "factoryId": str(
                result.get("factory_id")
                or result.get("factoryId")
                or response.get("FactoryID")
                or ""
            ),
            "fiscalSign": str(
                result.get("fiscal_sign")
                or result.get("fiscalSign")
                or response.get("FiscalSign")
                or ""
            ),
            "qrUrl": str(
                result.get("qr_code_url")
                or result.get("qrCodeUrl")
                or response.get("QRCodeURL")
                or ""
            ),
            "registeredAt": _local_datetime(receipt.fiscal_registered_at),
        },
        "system": {"copyNumber": 1, "isReprint": False},
    }


def build_order_precheck_print_snapshot(*, order) -> dict:
    restaurant = order.restaurant
    table_name, table_number, hall_name, zone_name, zone_display = _table_parts(order)
    active_items = order.items.exclude(
        status=order.items.model.Status.CANCELLED
    ).select_related("catalog_item").prefetch_related("modifiers")
    total = _money(order.total)
    subtotal = _money(order.subtotal)
    calculated_total = _money(order.calculated_total)
    vat_enabled = bool(getattr(restaurant, "vat_enabled", False))
    vat_percent = getattr(restaurant, "vat_percent", 0) or 0

    return {
        "restaurant": {
            "name": restaurant.name,
            "legalName": restaurant.legal_name or restaurant.name,
            "address": restaurant.address,
            "phone": restaurant.phone,
            "social": getattr(restaurant, "social", ""),
            "taxNumber": restaurant.tax_number,
        },
        "order": {
            "id": str(order.id),
            "displayNumber": str(order.display_name or order.order_number),
            "channel": order.channel,
            "channelLabel": _channel_label(order),
            "table": table_name,
            "tableNumber": table_number,
            "hall": hall_name,
            "zone": zone_name,
            "zoneDisplay": zone_display,
            "guestCount": int(order.guest_count or 0),
            "openedAt": _local_datetime(order.created_at),
            "waiter": order.opened_by.full_name if order.opened_by_id and order.opened_by else "",
            "cashier": order.cashier.full_name if order.cashier_id and order.cashier else "",
            "note": order.note or "",
            "deliveryPhone": order.delivery_phone or "",
            "deliveryAddress": order.delivery_address or "",
        },
        "items": _aggregate_print_items(
            active_items,
            vat_enabled=vat_enabled,
            vat_percent=vat_percent,
            include_vat=True,
        ),
        "precheck": {"printedAt": _local_datetime(timezone.now())},
        "totals": {
            "subtotal": subtotal,
            "serviceFee": _money(getattr(order, "service_fee", 0)) or max(calculated_total - subtotal, 0),
            **_service_fee_totals(order),
            **(
                {
                    "calculatedTotal": calculated_total,
                    "totalAdjustment": total - calculated_total,
                }
                if total != calculated_total
                else {}
            ),
            "vat": _included_vat(amount=total, percent=vat_percent) if vat_enabled else 0,
            "vatPercent": _json_number(vat_percent),
            "total": total,
        },
        "system": {"copyNumber": 1, "isReprint": False},
    }


def _build_kitchen_print_snapshot(*, ticket, items: list[dict], kitchen: dict | None = None) -> dict:
    order = ticket.order
    restaurant = ticket.restaurant
    table_name, table_number, hall_name, zone_name, zone_display = _table_parts(order)
    kitchen_snapshot = {
        "ticketNumber": f"K-{str(ticket.id)[-6:].upper()}",
        "prepStation": ticket.prep_station.name,
        "createdAt": _local_datetime(ticket.created_at),
        "dispatchNumber": ticket.dispatch_number,
        "isAddition": ticket.dispatch_number > 1,
    }
    kitchen_snapshot.update(kitchen or {})
    return {
        "restaurant": {
            "name": restaurant.name,
            "legalName": restaurant.legal_name or restaurant.name,
            "address": restaurant.address,
            "phone": restaurant.phone,
            "social": getattr(restaurant, "social", ""),
            "taxNumber": restaurant.tax_number,
        },
        "order": {
            "id": str(order.id),
            "displayNumber": str(order.display_name or order.order_number),
            "channel": order.channel,
            "channelLabel": _channel_label(order),
            "table": table_name,
            "tableNumber": table_number,
            "hall": hall_name,
            "zone": zone_name,
            "zoneDisplay": zone_display,
            "guestCount": int(order.guest_count or 0),
            "openedAt": _local_datetime(order.created_at),
            "waiter": order.opened_by.full_name
            if order.opened_by_id and order.opened_by
            else "",
            "cashier": order.cashier.full_name
            if order.cashier_id and order.cashier
            else "",
            "note": order.note or "",
            "deliveryPhone": order.delivery_phone or "",
            "deliveryAddress": order.delivery_address or "",
        },
        "items": items,
        "totals": {"total": sum(_money(item["lineTotal"]) for item in items)},
        "kitchen": kitchen_snapshot,
        "system": {"copyNumber": 1, "isReprint": False},
    }


def build_kitchen_print_snapshot(*, ticket) -> dict:
    order = ticket.order
    queryset = order.items.filter(kitchen_ticket_line__ticket=ticket)
    if not queryset.exists():
        queryset = order.items.filter(prep_station=ticket.prep_station)
    queryset = (
        queryset.exclude(status=order.items.model.Status.CANCELLED)
        .select_related("catalog_item")
        .prefetch_related("modifiers")
    )
    return _build_kitchen_print_snapshot(
        ticket=ticket,
        items=_aggregate_print_items(queryset),
    )


def build_kitchen_cancellation_print_snapshot(
    *, ticket, order_item, quantity_delta
) -> dict:
    quantity_delta = Decimal(str(quantity_delta))
    if quantity_delta >= 0 or -quantity_delta > Decimal(order_item.quantity or 0):
        raise ValueError(
            "Kitchen cancellation quantity delta must remove part or all of the order item."
        )
    normalized_quantity_delta = _json_number(quantity_delta)
    line_total_delta = (
        -_money(order_item.line_total)
        if -quantity_delta == Decimal(order_item.quantity or 0)
        else int(
            (quantity_delta * Decimal(order_item.unit_price or 0)).quantize(
                Decimal("1"),
                rounding=ROUND_HALF_UP,
            )
        )
    )
    item, _modifier_signature, _item_note = _print_item_values(order_item)
    item.update(
        {
            "name": f"BEKOR QILISH: {item['name']}",
            "quantity": normalized_quantity_delta,
            "lineTotal": line_total_delta,
            "isCancellation": True,
            "operationLabel": "BEKOR QILISH",
            "quantityDelta": normalized_quantity_delta,
        }
    )
    return _build_kitchen_print_snapshot(
        ticket=ticket,
        items=[item],
        kitchen={
            "ticketNumber": f"C-{str(ticket.id)[-6:].upper()}",
            "createdAt": _local_datetime(order_item.updated_at),
            "isAddition": False,
            "isCancellation": True,
            "operation": "cancellation",
            "operationLabel": "BEKOR QILISH",
            "quantityDelta": normalized_quantity_delta,
            "originalTicketNumber": f"K-{str(ticket.id)[-6:].upper()}",
        },
    )
