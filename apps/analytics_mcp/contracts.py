from datetime import date, timedelta
from typing import Literal
from uuid import UUID

from django.conf import settings
from pydantic import BaseModel, ConfigDict, Field, model_validator

from apps.reporting.services import ReportPeriod
from common.utils.date import tashkent_day_bounds, tashkent_now
from .policy import AnalyticsError


class InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BranchInput(InputModel):
    branch_ids: list[UUID] | None = Field(
        default=None,
        min_length=1,
        max_length=50,
        description="IDs from list_branches. Omit to include all consented, currently accessible branches.",
    )


class PeriodInput(BranchInput):
    period: Literal["today", "yesterday", "last_7_days", "previous_week", "range"] = (
        "today"
    )
    start_date: date | None = None
    end_date: date | None = None

    @model_validator(mode="after")
    def validate_range(self):
        if self.period == "range":
            if self.start_date is None or self.end_date is None:
                raise ValueError(
                    "range requires start_date and end_date (inclusive YYYY-MM-DD)."
                )
        elif self.start_date is not None or self.end_date is not None:
            raise ValueError("Explicit dates require period=range.")
        return self


class SummaryInput(PeriodInput):
    compare_previous: bool = False


class SeriesInput(PeriodInput):
    granularity: Literal["day", "hour"] = "day"


class TopProductsInput(PeriodInput):
    sort_by: Literal["revenue", "quantity"] = "revenue"
    limit: int = Field(default=10, ge=1, le=50)
    sale_unit: Literal["piece", "kg"] | None = None

    @model_validator(mode="after")
    def quantity_unit(self):
        if self.sort_by == "quantity" and self.sale_unit is None:
            raise ValueError(
                "quantity ranking requires sale_unit so kilograms and pieces are not mixed."
            )
        return self


class ChartInput(InputModel):
    report_id: UUID


class RankedInput(PeriodInput):
    limit: int = Field(default=10, ge=1, le=50)


class Envelope(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    report_type: str
    report_id: str | None = None
    generated_at: str
    timezone: Literal["Asia/Tashkent"] = "Asia/Tashkent"
    branches: list[dict]
    presentation: dict = Field(default_factory=dict)
    currency: str | None
    period: dict | None = None
    metric_basis: dict
    data_freshness: dict
    warnings: list[str]
    data: dict


def resolve_period(params, now=None):
    now = now or tashkent_now()
    today = now.date()
    if params.period == "range":
        start_date, end_date = params.start_date, params.end_date
    elif params.period == "yesterday":
        start_date = end_date = today - timedelta(days=1)
    elif params.period == "last_7_days":
        start_date, end_date = today - timedelta(days=6), today
    elif params.period == "previous_week":
        end_date = today - timedelta(days=today.weekday() + 1)
        start_date = end_date - timedelta(days=6)
    else:
        start_date = end_date = today
    if start_date > end_date or end_date > today:
        raise AnalyticsError(
            "invalid_period", "Dates must be ordered and cannot be in the future."
        )
    if (end_date - start_date).days + 1 > settings.MCP_MAX_DAYS:
        raise AnalyticsError(
            "invalid_period", f"Maximum date range is {settings.MCP_MAX_DAYS} days."
        )
    start, _ = tashkent_day_bounds(start_date)
    _, end = tashkent_day_bounds(end_date)
    effective_end = min(end, now)
    period = ReportPeriod(
        "range", start, effective_end, f"{start_date}:{end_date}", "", ""
    )
    metadata = {
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "start_inclusive": start.isoformat(),
        "end_exclusive": effective_end.isoformat(),
        "is_partial": effective_end < end,
    }
    return period, metadata
