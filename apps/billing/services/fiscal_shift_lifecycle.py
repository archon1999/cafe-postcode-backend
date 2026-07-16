from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.billing.helpers import get_fiscal_shift_session_model

FiscalShiftSession = get_fiscal_shift_session_model()


class FiscalShiftLifecycleMixin:
    def open_fiscal_shift(
        self, *, restaurant, cash_desk=None, opened_by=None, provider_result=None
    ):
        existing = FiscalShiftSession.objects.filter(
            restaurant=restaurant,
            cash_desk=cash_desk,
            status=FiscalShiftSession.Status.OPEN,
        ).first()
        if existing is not None:
            raise ValidationError({"detail": "Fiscal smena allaqachon ochiq."})

        result = (
            provider_result
            if provider_result is not None
            else self._open_fiscal_shift_with_gateway(
                restaurant=restaurant, cash_desk=cash_desk
            )
        )
        FiscalShiftSession.objects.create(
            restaurant=restaurant,
            cash_desk=cash_desk,
            opened_by=opened_by,
            status=FiscalShiftSession.Status.OPEN,
            provider=str(result.get("provider") or ""),
            terminal_id=self._terminal_id_from_fiscal_result(result),
            opened_at=timezone.now(),
            open_payload=result,
        )
        return result

    def ensure_fiscal_shift_open(self, *, restaurant, cash_desk=None, opened_by=None):
        existing = self._get_active_fiscal_session(
            restaurant=restaurant, cash_desk=cash_desk
        )
        if existing is not None:
            return None
        try:
            return self.open_fiscal_shift(
                restaurant=restaurant, cash_desk=cash_desk, opened_by=opened_by
            )
        except ValueError as error:
            detail = str(error)
            if "not configured" in detail or "Unsupported fiscal provider" in detail:
                return None
            raise

    def has_open_fiscal_shift(self, *, restaurant, cash_desk=None):
        return (
            self._get_active_fiscal_session(restaurant=restaurant, cash_desk=cash_desk)
            is not None
        )

    def close_fiscal_shift(
        self, *, restaurant, cash_desk=None, closed_by=None, provider_result=None
    ):
        session = self._get_active_fiscal_session(
            restaurant=restaurant, cash_desk=cash_desk
        )
        if session is None:
            return {
                "skipped": True,
                "reason": "fiscal_shift_not_open",
                "detail": "Fiscal smena ochilmagan.",
            }
        paid_at_from = session.opened_at if session is not None else None
        paid_at_to = timezone.now()
        self.ensure_no_unresolved_fiscal_payments(
            restaurant=restaurant,
            cash_desk=cash_desk,
            paid_at_from=paid_at_from,
            paid_at_to=paid_at_to,
        )
        report = self.build_fiscal_shift_report(
            restaurant=restaurant,
            cash_desk=cash_desk,
            paid_at_from=paid_at_from,
            paid_at_to=paid_at_to,
        )
        result = (
            provider_result
            if provider_result is not None
            else self._close_fiscal_shift_with_gateway(
                restaurant=restaurant, cash_desk=cash_desk
            )
        )
        if session is not None:
            close_payload = {
                "provider_result": result,
                "reports": report,
                "closed_at": timezone.now().isoformat(),
            }
            session.status = FiscalShiftSession.Status.CLOSED
            session.closed_by = closed_by
            session.closed_at = timezone.now()
            session.close_payload = close_payload
            if not session.provider:
                session.provider = str(result.get("provider") or "")
            if not session.terminal_id:
                session.terminal_id = self._terminal_id_from_fiscal_result(result)
            session.save(
                update_fields=[
                    "status",
                    "closed_by",
                    "closed_at",
                    "close_payload",
                    "provider",
                    "terminal_id",
                    "updated_at",
                ]
            )
        return {
            "result": result,
            "provider_report": result.get("provider_report")
            if isinstance(result, dict)
            else None,
            "report": report,
            "reports": report,
        }

    @staticmethod
    def _open_fiscal_shift_with_gateway(*, restaurant, cash_desk):
        from . import cash_shift as cash_shift_module

        return cash_shift_module.open_fiscal_shift(
            restaurant=restaurant, cash_desk=cash_desk
        )

    @staticmethod
    def _close_fiscal_shift_with_gateway(*, restaurant, cash_desk):
        from . import cash_shift as cash_shift_module

        return cash_shift_module.close_fiscal_shift(
            restaurant=restaurant, cash_desk=cash_desk
        )

    def _get_active_fiscal_session(self, *, restaurant, cash_desk=None):
        return (
            FiscalShiftSession.objects.filter(
                restaurant=restaurant,
                cash_desk=cash_desk,
                status=FiscalShiftSession.Status.OPEN,
            )
            .order_by("-opened_at")
            .first()
        )

    @staticmethod
    def _terminal_id_from_fiscal_result(result):
        response = result.get("response") if isinstance(result, dict) else {}
        if not isinstance(response, dict):
            response = {}
        provider_report = (
            result.get("provider_report") if isinstance(result, dict) else {}
        )
        z_info = (
            provider_report.get("z_info") if isinstance(provider_report, dict) else {}
        )
        if not isinstance(z_info, dict):
            z_info = {}
        return str(
            response.get("TerminalID")
            or response.get("Fiscal")
            or result.get("terminal_id")
            or z_info.get("TerminalID")
            or ""
        ).strip()

    @staticmethod
    def validate_edge_fiscal_shift_result(*, result, cash_desk):
        if not isinstance(result, dict) or result.get("ok") is not True:
            raise ValidationError(
                {"edgeFiscalResult": "Local fiscal shift result is invalid."}
            )
        integration = (
            getattr(cash_desk, "fiscal_integration", None)
            if cash_desk is not None
            else None
        )
        expected_provider = str(getattr(integration, "provider", "") or "").strip()
        provider = str(result.get("provider") or "").strip()
        if not expected_provider or provider != expected_provider:
            raise ValidationError(
                {
                    "edgeFiscalResult": "Fiscal result provider does not match the active cash desk."
                }
            )
        return dict(result)
