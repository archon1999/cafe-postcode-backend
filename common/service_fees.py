from decimal import Decimal, ROUND_HALF_DOWN, ROUND_HALF_UP

from django.db import models
from django.utils import timezone
from common.service_fee_formulas import FormulaError, evaluate_formula
from common.service_fee_formulas.catalog import normalize_definition


class ServiceFeeMode(models.TextChoices):
    PERCENTAGE = "percentage", "Percentage"
    HOURLY = "hourly", "Hourly"
    FORMULA = "formula", "Formula"


SERVICE_FEE_SCOPES = ("restaurant", "hall", "table")
SERVICE_FEE_BILLING_INTERVAL_MINUTES = 5
SERVICE_FEE_MINIMUM_BILLABLE_MINUTES = 60
SERVICE_FEE_AMOUNT_ROUNDING_QUANTUM = Decimal("1E3")


def _json_number(value):
    number = Decimal(str(value or 0))
    return int(number) if number == number.to_integral_value() else float(number)


def snapshot_service_fee_source(*, scope: str, source) -> dict | None:
    if scope not in SERVICE_FEE_SCOPES or source is None:
        return None
    if not bool(getattr(source, "service_fee_enabled", False)):
        return None

    mode = str(
        getattr(source, "service_fee_mode", ServiceFeeMode.PERCENTAGE)
        or ServiceFeeMode.PERCENTAGE
    )
    component = {
        "scope": scope,
        "source_name": str(getattr(source, "name", "") or ""),
        "mode": mode,
    }
    if mode == ServiceFeeMode.FORMULA:
        component['formula'] = normalize_definition(getattr(source, 'service_fee_formula', None))
        return component
    if mode == ServiceFeeMode.HOURLY:
        hourly_rate = max(int(getattr(source, "service_fee_hourly_rate", 0) or 0), 0)
        if hourly_rate <= 0:
            return None
        component["hourly_rate"] = hourly_rate
        return component

    percent = max(Decimal(str(getattr(source, "service_fee_percent", 0) or 0)), Decimal("0"))
    if percent <= 0:
        return None
    component["mode"] = ServiceFeeMode.PERCENTAGE
    component["percent"] = _json_number(percent)
    return component


def build_service_fee_snapshot(*, restaurant=None, hall=None, table=None, guest_count=1) -> list[dict]:
    components = []
    for scope, source in (
        ("restaurant", restaurant),
        ("hall", hall),
        ("table", table),
    ):
        component = snapshot_service_fee_source(scope=scope, source=source)
        if component is not None:
            if component['mode'] == ServiceFeeMode.FORMULA:
                component['guest_count'] = guest_count
            components.append(component)
    return components


def normalize_service_fee_snapshot(value) -> list[dict]:
    normalized = []
    if not isinstance(value, list):
        return normalized
    for raw in value:
        if not isinstance(raw, dict):
            continue
        scope = str(raw.get("scope") or "")
        if scope not in SERVICE_FEE_SCOPES:
            continue
        mode = str(raw.get("mode") or ServiceFeeMode.PERCENTAGE)
        component = {
            "scope": scope,
            "source_name": str(raw.get("source_name") or raw.get("sourceName") or ""),
            "mode": mode,
        }
        if mode == ServiceFeeMode.FORMULA:
            component['formula'] = normalize_definition(raw.get('formula'))
            component['guest_count'] = int(raw.get('guest_count', raw.get('guestCount', 1)))
        elif mode == ServiceFeeMode.HOURLY:
            hourly_rate = max(int(raw.get("hourly_rate") or raw.get("hourlyRate") or 0), 0)
            if hourly_rate <= 0:
                continue
            component["hourly_rate"] = hourly_rate
        else:
            percent = max(Decimal(str(raw.get("percent") or 0)), Decimal("0"))
            if percent <= 0:
                continue
            component["mode"] = ServiceFeeMode.PERCENTAGE
            component["percent"] = _json_number(percent)
        normalized.append(component)
    return normalized


def service_fee_billable_minutes(*, started_at, ended_at=None) -> int:
    if started_at is None:
        return 0
    ended_at = ended_at or timezone.now()
    seconds = max((ended_at - started_at).total_seconds(), 0)
    interval_seconds = SERVICE_FEE_BILLING_INTERVAL_MINUTES * 60
    complete_interval_minutes = (
        int(seconds // interval_seconds) * SERVICE_FEE_BILLING_INTERVAL_MINUTES
    )
    return max(SERVICE_FEE_MINIMUM_BILLABLE_MINUTES, complete_interval_minutes)


def calculate_percentage_service_fee(*, subtotal: int, percent) -> int:
    rate = max(Decimal(str(percent or 0)), Decimal("0"))
    if subtotal <= 0 or rate <= 0:
        return 0
    return int(
        (Decimal(subtotal) * rate / Decimal("100")).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
    )


def calculate_hourly_service_fee(*, hourly_rate: int, minutes: int) -> int:
    if hourly_rate <= 0 or minutes <= 0:
        return 0
    return int(
        (Decimal(hourly_rate) * Decimal(minutes) / Decimal("60")).quantize(
            SERVICE_FEE_AMOUNT_ROUNDING_QUANTUM,
            rounding=ROUND_HALF_DOWN,
        )
    )


def calculate_service_fee_components(
    *,
    snapshot,
    subtotal: int,
    started_at=None,
    ended_at=None,
    guest_count=1,
) -> list[dict]:
    snapshot = normalize_service_fee_snapshot(snapshot)
    minutes = service_fee_billable_minutes(started_at=started_at, ended_at=ended_at)
    components = []
    ended_at = ended_at or timezone.now()
    for configured in snapshot:
        component = dict(configured)
        if configured['mode'] == ServiceFeeMode.FORMULA:
            formula = configured['formula']
            if started_at is None:
                raise FormulaError('Formula service fee requires a session start time.')
            result = evaluate_formula(
                formula['source'], formula['parameters'], subtotal=max(0, int(subtotal or 0)),
                started_at=started_at, calculated_at=ended_at,
                guest_count=configured.get('guest_count', guest_count), timezone_name=formula['timezone'],
            )
            component['amount'] = result['amount']
            component['duration_minutes'] = max(0, (ended_at - started_at).total_seconds() / 60)
            component['time_dependent'] = result['time_dependent']
            component['calculation'] = result
        elif configured["mode"] == ServiceFeeMode.HOURLY:
            component["duration_minutes"] = minutes
            component['amount'] = calculate_hourly_service_fee(
                hourly_rate=int(configured['hourly_rate']), minutes=minutes,
            )
        else:
            component['amount'] = calculate_percentage_service_fee(
                subtotal=int(subtotal or 0), percent=configured['percent'],
            )
        components.append(component)
    return components


def service_fee_percent_total(snapshot) -> Decimal:
    return sum(
        (
            Decimal(str(component.get("percent") or 0))
            for component in normalize_service_fee_snapshot(snapshot)
            if component["mode"] == ServiceFeeMode.PERCENTAGE
        ),
        Decimal("0"),
    )


def validate_service_fee_configuration(*, enabled, mode, percent, hourly_rate, formula=None) -> dict:
    if not enabled:
        return {}
    if mode == ServiceFeeMode.FORMULA:
        try:
            normalize_definition(formula)
        except FormulaError as error:
            return {'service_fee_formula': str(error)}
        return {}
    if mode == ServiceFeeMode.HOURLY:
        if int(hourly_rate or 0) <= 0:
            return {"service_fee_hourly_rate": "Hourly service fee rate must be greater than zero."}
        return {}
    rate = Decimal(str(percent or 0))
    if rate < 1 or rate > 99:
        return {"service_fee_percent": "Service fee percent must be between 1 and 99."}
    return {}
