from decimal import Decimal, ROUND_HALF_UP


def _decimal_text(value: Decimal, *, places: int = 2) -> str:
    quantum = Decimal(1).scaleb(-places)
    text = format(value.quantize(quantum, rounding=ROUND_HALF_UP), "f")
    text = text.rstrip("0").rstrip(".")
    return text.replace(".", ",")


def format_compact_money(value: int, *, include_currency: bool = True) -> str:
    value = int(value or 0)
    absolute = abs(value)
    sign = "-" if value < 0 else ""
    if absolute >= 1_000_000:
        text = f"{sign}{_decimal_text(Decimal(absolute) / Decimal(1_000_000))} mln"
    elif absolute >= 1_000:
        thousands = (Decimal(absolute) / Decimal(1_000)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        text = f"{sign}{thousands} ming"
    else:
        text = f"{value}"
    return f"{text} so‘m" if include_currency else text


def format_mln_money(value: int, *, signed: bool = False) -> str:
    value = int(value or 0)
    prefix = "+" if signed and value > 0 else ""
    amount = _decimal_text(Decimal(value) / Decimal(1_000_000))
    return f"{prefix}{amount}"


def format_percent(value: float) -> str:
    value = float(value or 0)
    prefix = "+" if value > 0 else ""
    text = _decimal_text(Decimal(str(value)), places=2)
    return f"{prefix}{text}%"


def build_weekly_grid(rows: list[dict]) -> str:
    day_names = ("Du", "Se", "Cho", "Pa", "Ju", "Sha", "Ya")
    headers = [f"{day_names[row['date'].weekday()]} {row['date'].day:02d}" for row in rows]
    values = [format_mln_money(row["sales_total"]) for row in rows]
    differences = [format_mln_money(row["sales_difference"], signed=True) for row in rows]
    width = max(6, *(len(value) for value in headers + values + differences))

    def line(values_to_render: list[str], *, align: str) -> str:
        if align == "right":
            return "│".join(value.rjust(width) for value in values_to_render)
        return "│".join(value.ljust(width) for value in values_to_render)

    return "\n".join(
        (
            line(headers, align="right"),
            line(values, align="right"),
            line(differences, align="right"),
        )
    )

