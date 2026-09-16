from dataclasses import dataclass, field
from datetime import date, timedelta

from django.conf import settings
from django.utils import timezone

from apps.users.models import User
from common.utils.date import tashkent_now
from .contracts import Envelope, PeriodInput, resolve_period
from .models import ReportSnapshot
from .policy import AnalyticsError, resolve_scope
from .registry import report_registry


@dataclass
class ReportContext:
    branches: tuple
    period: object = None
    start_date: date | None = None
    end_date: date | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def branch_metadata(self):
        return [
            {"id": str(r.pk), "name": r.name, "currency": r.currency}
            for r in self.branches
        ]


def execute_report(principal, name, arguments):
    definition = report_registry().get(name)
    if definition is None:
        raise AnalyticsError("unknown_tool", "Unknown analytics tool.")
    params = definition.input_model.model_validate(arguments)
    branches = resolve_scope(principal, params.branch_ids)
    if definition.max_branches and len(branches) > definition.max_branches:
        raise AnalyticsError(
            "too_many_branches",
            f"Select at most {definition.max_branches} branches for one report.",
        )
    # Extension modules have an explicit role/entitlement boundary in addition to OAuth.
    user = User.objects.get(pk=principal.user_id)
    if definition.permission not in user.permission_codes or any(
        definition.permission not in branch.entitlement.get_effective_permission_codes()
        for branch in branches
    ):
        raise AnalyticsError(
            "access_denied", "This report is not enabled for the selected branches."
        )
    context = ReportContext(branches)
    metadata = None
    generated_at = tashkent_now()
    if isinstance(params, PeriodInput):
        context.period, metadata = resolve_period(params, generated_at)
        context.start_date = date.fromisoformat(metadata["start_date"])
        context.end_date = date.fromisoformat(metadata["end_date"])
        if metadata["is_partial"]:
            context.warnings.append(
                "The current day is incomplete; values cover only the displayed cutoff."
            )
    currencies = {r.currency for r in branches}
    if len(currencies) != 1 and definition.requires_single_currency:
        raise AnalyticsError(
            "mixed_currencies",
            "Select branches with one currency or use compare_branches.",
        )
    data = definition.handler(context, params)
    result = Envelope(
        report_type=name,
        generated_at=generated_at.isoformat(),
        branches=context.branch_metadata,
        presentation={
            "scope_mode": "single" if len(branches) == 1 else "multiple",
            "show_branches": len(branches) > 1,
            "restaurant_name": branches[0].name if len(branches) == 1 else None,
        },
        currency=next(iter(currencies)) if len(currencies) == 1 else None,
        period=metadata,
        metric_basis=definition.metric_basis,
        data_freshness={
            "status": "unknown",
            "source": "central_database",
            "sync_watermark": None,
        },
        warnings=context.warnings
        + [
            "Offline POS transactions not yet synchronized to the central server are not included."
        ],
        data=data,
    ).model_dump(mode="json")
    if definition.persist:
        snapshot = ReportSnapshot(
            connection_id=principal.connection_id,
            restaurant_ids=[str(r.pk) for r in branches],
            payload=result,
            expires_at=timezone.now()
            + timedelta(seconds=settings.MCP_REPORT_TTL_SECONDS),
        )
        result["report_id"] = str(snapshot.pk)
        snapshot.save()
    return result


def load_chart(principal, report_id):
    snapshot = ReportSnapshot.objects.filter(
        pk=report_id,
        connection_id=principal.connection_id,
        expires_at__gt=timezone.now(),
    ).first()
    if snapshot is None:
        raise AnalyticsError(
            "report_unavailable",
            "Report expired or unavailable. Fetch a new sales timeseries.",
        )
    resolve_scope(principal, snapshot.restaurant_ids)
    if snapshot.payload["report_type"] != "get_sales_timeseries":
        raise AnalyticsError(
            "invalid_report", "The chart requires a sales timeseries report."
        )
    return snapshot.payload
