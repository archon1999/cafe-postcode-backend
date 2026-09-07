from decimal import Decimal, ROUND_FLOOR


def allocate_fiscal_totals(values, *, target_total: int) -> list[int]:
    """Scale non-negative receipt lines so their integer sum equals target_total."""

    normalized = [max(int(value or 0), 0) for value in values]
    target_total = max(int(target_total or 0), 0)
    if not normalized:
        return []
    source_total = sum(normalized)
    if source_total <= 0:
        result = [0] * len(normalized)
        result[-1] = target_total
        return result
    if source_total == target_total:
        return normalized

    exact = [Decimal(value) * Decimal(target_total) / Decimal(source_total) for value in normalized]
    result = [int(value.quantize(Decimal('1'), rounding=ROUND_FLOOR)) for value in exact]
    remainder = target_total - sum(result)
    ranked = sorted(
        range(len(exact)),
        key=lambda index: (exact[index] - Decimal(result[index]), normalized[index], -index),
        reverse=True,
    )
    for index in ranked[:remainder]:
        result[index] += 1
    return result


def settled_order_lines(order):
    """Canonical line ordering/allocation shared by fiscal and printed receipts."""
    order_items = (
        order.items.exclude(status=order.items.model.Status.CANCELLED)
        .select_related('catalog_item', 'catalog_item__category').prefetch_related('modifiers')
        .order_by('created_at', 'id')
    )
    order_items = list(order_items)
    service_fee = max(int(order.calculated_total or 0) - int(order.subtotal or 0), 0)
    service_fee_components = [
        component
        for component in order.get_service_fee_components()
        if int(component.get('amount') or 0) > 0
    ]
    if service_fee and not service_fee_components:
        service_fee_components = [{'scope': 'service', 'amount': service_fee}]
    adjusted_totals = allocate_fiscal_totals(
        [
            *(int(item.line_total or 0) for item in order_items),
            *(int(component['amount']) for component in service_fee_components),
        ],
        target_total=int(order.total or 0),
    )
    return order_items, service_fee_components, adjusted_totals
