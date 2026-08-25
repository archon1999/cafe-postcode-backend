from decimal import Decimal, ROUND_HALF_UP


TELEGRAM_MESSAGE_TEXT_LIMIT = 4096


def split_telegram_message(
    text: str,
    *,
    limit: int = TELEGRAM_MESSAGE_TEXT_LIMIT,
) -> list[str]:
    """Split report HTML into Bot API-safe messages without breaking content blocks."""
    text = text.strip()
    if not text:
        return []
    if limit <= 0:
        raise ValueError("Telegram message limit must be positive.")
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    current_blocks: list[str] = []
    for block in text.split("\n\n"):
        candidate = "\n\n".join((*current_blocks, block))
        if current_blocks and len(candidate) > limit:
            chunks.append("\n\n".join(current_blocks).rstrip())
            current_blocks = []

        if len(block) > limit:
            chunks.extend(_split_telegram_lines(block, limit=limit))
        else:
            current_blocks.append(block)

    if current_blocks:
        chunks.append("\n\n".join(current_blocks).rstrip())
    return [chunk for chunk in chunks if chunk]


def _split_telegram_lines(text: str, *, limit: int) -> list[str]:
    chunks: list[str] = []
    current_lines: list[str] = []
    for line in text.splitlines():
        if len(line) > limit:
            raise ValueError("A Telegram report line exceeds the message length limit.")

        candidate = "\n".join((*current_lines, line))
        if current_lines and len(candidate) > limit:
            chunks.append("\n".join(current_lines).rstrip())
            current_lines = [] if not line else [line]
            continue
        current_lines.append(line)

    if current_lines:
        chunks.append("\n".join(current_lines).rstrip())
    return [chunk for chunk in chunks if chunk]


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


def format_quantity(value: int | float) -> str:
    quantity = Decimal(str(value or 0))
    text = format(quantity.normalize(), "f")
    return text.replace(".", ",")


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
