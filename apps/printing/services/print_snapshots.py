from decimal import Decimal, ROUND_HALF_UP

from django.db.models import Sum
from django.utils import timezone


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


def _channel_label(order) -> str:
    labels = {
        "hall": "Zal",
        "takeaway": "Soboy",
        "delivery": "Dostavka",
        "online": "Online",
    }
    return labels.get(str(order.channel or ""), str(order.channel or ""))


def _table_parts(order) -> tuple[str, str]:
    session = getattr(order, "table_session", None)
    table = getattr(session, "table", None) if session is not None else None
    hall = getattr(session, "hall", None) if session is not None else None
    return (str(getattr(table, "name", "") or ""), str(getattr(hall, "name", "") or ""))


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


def _aggregate_print_items(
    queryset, *, vat_enabled=False, vat_percent=0, include_vat=False
) -> list[dict]:
    aggregated = {}
    for item in queryset.order_by("created_at"):
        name = item.catalog_item.name if item.catalog_item_id else item.name_snapshot
        unit_price = _money(item.unit_price)
        note = item.note or ""
        key = (str(item.catalog_item_id or name), note, unit_price)
        current = aggregated.setdefault(
            key,
            {
                "name": name,
                "quantity": 0,
                "unitPrice": unit_price,
                "lineTotal": 0,
                "note": note,
            },
        )
        current["quantity"] += int(item.quantity or 0)
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
    table_name, hall_name = _table_parts(order)
    active_items = order.items.exclude(
        status=order.items.model.Status.CANCELLED
    ).select_related("catalog_item")
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
            "hall": hall_name,
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
            "serviceFee": max(total - subtotal, 0),
            "serviceFeePercent": _json_number(
                getattr(restaurant, "service_fee_percent", 0)
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


def build_kitchen_print_snapshot(*, ticket) -> dict:
    order = ticket.order
    restaurant = ticket.restaurant
    table_name, hall_name = _table_parts(order)
    queryset = (
        order.items.filter(prep_station=ticket.prep_station)
        .exclude(status=order.items.model.Status.CANCELLED)
        .select_related("catalog_item")
    )
    items = _aggregate_print_items(queryset)
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
            "hall": hall_name,
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
        "kitchen": {
            "ticketNumber": f"K-{str(ticket.id)[-6:].upper()}",
            "prepStation": ticket.prep_station.name,
            "createdAt": _local_datetime(ticket.created_at),
        },
        "system": {"copyNumber": 1, "isReprint": False},
    }
