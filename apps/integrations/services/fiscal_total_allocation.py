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
