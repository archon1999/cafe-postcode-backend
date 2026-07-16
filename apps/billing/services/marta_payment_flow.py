from django.db.models import Sum
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from rest_framework.exceptions import ValidationError

from apps.billing.helpers import get_payment_model
from apps.integrations.services.marta_softpos import (
    DEFAULT_AMOUNT_MULTIPLIER,
    DEFAULT_TIMEOUT_SECONDS,
    JAVA_LONG_MAX,
)
from apps.sales.helpers import get_order_model
from apps.sales.services import validate_order_markings
from common.api.permissions import (
    POS_FISCAL_RECEIPTS_SKIP_PERMISSION,
    has_permission_code,
)

Order = get_order_model()
Payment = get_payment_model()


class MartaPaymentFlowMixin:
    def initiate_marta_card_payment(
        self,
        *,
        order: Order,
        amount,
        register_fiscal=True,
        received_by,
        cash_shift=None,
    ):
        from apps.billing.serializers import PaymentSerializer

        state_service = self.state_service_class()
        state_service.ensure_order_can_be_paid(order=order)
        state_service.ensure_delivery_details(order=order)
        if self._should_submit_before_payment(order=order):
            self.order_submission_service_class().submit(order)

        self._validate_shift(order=order, cash_shift=cash_shift)
        if not register_fiscal and not has_permission_code(
            received_by, POS_FISCAL_RECEIPTS_SKIP_PERMISSION
        ):
            raise ValidationError(
                {
                    "register_fiscal": _(
                        "You do not have permission to skip fiscal registration."
                    )
                }
            )
        validate_order_markings(order)
        serializer = PaymentSerializer(
            data={
                "method": Payment.Method.CARD,
                "amount": amount,
                "register_fiscal": register_fiscal,
            }
        )
        serializer.is_valid(raise_exception=True)
        amount = serializer.validated_data["amount"]

        cash_desk = cash_shift.cash_desk
        if Payment.Method.CARD not in set(cash_desk.enabled_payment_methods or []):
            raise ValidationError(
                {
                    "method": _(
                        "Selected payment method is disabled on the active cash desk."
                    )
                }
            )

        config = getattr(cash_desk, "payment_integration", None)
        if (
            config is None
            or config.kind != "payment"
            or config.provider != "marta-softpos"
            or not config.is_enabled
        ):
            raise ValidationError(
                {
                    "detail": _(
                        "MARTA SoftPOS payment integration is not configured for the active cash desk."
                    )
                }
            )

        self._validate_payment_amount(order=order, amount=amount)
        settings = dict(config.settings or {})
        if str(settings.get("transport") or "").strip() == "local-agent":
            raise ValidationError(
                {
                    "detail": _(
                        "MARTA browser-direct payment flow is disabled. Refresh POS and use the card payment flow through the local agent."
                    )
                }
            )
        endpoint_url = str(
            settings.get("endpoint_url") or settings.get("endpointUrl") or ""
        ).rstrip("/")
        if not endpoint_url:
            raise ValidationError(
                {"detail": _("MARTA SoftPOS endpoint URL is not configured.")}
            )

        payment = serializer.save(
            order=order,
            received_by=received_by,
            cash_shift=cash_shift,
            cash_desk=cash_desk,
        )

        amount_multiplier = self._positive_int(
            settings.get("amount_multiplier") or settings.get("amountMultiplier"),
            DEFAULT_AMOUNT_MULTIPLIER,
        )
        timeout_seconds = self._positive_int(
            settings.get("timeout_seconds") or settings.get("timeoutSeconds"),
            int(DEFAULT_TIMEOUT_SECONDS),
        )
        pid = self._marta_pid(payment=payment)
        tax_number = str(
            settings.get("tax_number")
            or settings.get("taxNumber")
            or getattr(order.restaurant, "tax_number", "")
            or ""
        ).strip()
        marta_payload = {
            "endpoint_url": endpoint_url,
            "endpointUrl": endpoint_url,
            "pid": pid,
            "amount": int(payment.amount or 0) * amount_multiplier,
            "amount_multiplier": amount_multiplier,
            "amountMultiplier": amount_multiplier,
            "tax_number": tax_number,
            "taxNumber": tax_number,
            "timeout_seconds": timeout_seconds,
            "timeoutSeconds": timeout_seconds,
        }
        payment.provider_payload = {
            "ok": False,
            "provider": "marta-softpos",
            "method": Payment.Method.CARD,
            "status": Payment.Status.PENDING,
            "reference": "",
            "pid": pid,
            "endpoint_url": endpoint_url,
            "amount_multiplier": amount_multiplier,
            "tax_number": tax_number,
            "timeout_seconds": timeout_seconds,
            "initiated_at": timezone.now().isoformat(),
        }
        payment.save(update_fields=["provider_payload", "updated_at"])
        return {"payment": payment, "marta": marta_payload}

    def complete_marta_terminal_payment(
        self, *, payment: Payment, terminal_result: dict, received_by
    ):
        if payment.method != Payment.Method.CARD:
            raise ValidationError(
                {
                    "detail": _(
                        "Only card payments can be completed with MARTA terminal result."
                    )
                }
            )
        if payment.status != Payment.Status.PENDING:
            raise ValidationError(
                {
                    "detail": _(
                        "Only pending card payments can be completed with MARTA terminal result."
                    )
                }
            )

        status = str(terminal_result.get("status") or "").strip().upper()
        params = (
            terminal_result.get("params")
            if isinstance(terminal_result.get("params"), dict)
            else {}
        )
        if "trx_id" in params and "trxId" not in params:
            params = {**params, "trxId": params["trx_id"]}
        request_id = str(
            terminal_result.get("requestId") or terminal_result.get("request_id") or ""
        )
        reference = str(
            params.get("trxId")
            or params.get("trx_id")
            or params.get("rrn")
            or request_id
            or ""
        )
        message = str(terminal_result.get("message") or "").strip()
        ok = terminal_result.get("ok") is True and status == "SUCCESS"
        previous_payload = dict(payment.provider_payload or {})
        debug = self._normalize_marta_debug_payload(terminal_result.get("debug") or {})
        provider_payload = {
            **previous_payload,
            "ok": ok,
            "provider": "marta-softpos",
            "method": Payment.Method.CARD,
            "reference": reference,
            "requestId": request_id,
            "status": status or "ERROR",
            "message": message,
            "params": params,
            "ac": terminal_result.get("ac") or params.get("ac"),
            "response": terminal_result.get("response") or terminal_result,
            "debug": debug,
            "browserError": terminal_result.get("browserError")
            or terminal_result.get("browser_error")
            or {},
            "processed_at": timezone.now().isoformat(),
        }

        payment.status = Payment.Status.SUCCEEDED if ok else Payment.Status.FAILED
        payment.external_ref = reference
        payment.provider_payload = provider_payload
        payment.paid_at = timezone.now() if ok else None
        payment.save(
            update_fields=[
                "status",
                "external_ref",
                "provider_payload",
                "paid_at",
                "updated_at",
            ]
        )

        if not ok:
            detail = (
                message
                or f"MARTA SoftPOS payment failed with status {status or 'ERROR'}."
            )
            return {
                "payment": payment,
                "receipt": None,
                "receipts": [],
                "order": payment.order,
                "detail": detail,
            }

        paid_before_current = (
            payment.order.payments.filter(status=Payment.Status.SUCCEEDED)
            .exclude(pk=payment.pk)
            .aggregate(total=Sum("amount"))
            .get("total")
            or 0
        )
        remaining_amount = max(
            0, int(payment.order.total or 0) - int(paid_before_current or 0)
        )
        if int(payment.amount or 0) > remaining_amount:
            payment.status = Payment.Status.FAILED
            payment.provider_payload = {
                **provider_payload,
                "ok": False,
                "status": "ERROR",
                "message": "Payment amount exceeds remaining total.",
            }
            payment.paid_at = None
            payment.save(
                update_fields=["status", "provider_payload", "paid_at", "updated_at"]
            )
            raise ValidationError(
                {"amount": _("Payment amount cannot exceed the remaining total.")}
            )

        return self._complete_successful_payment(
            order=payment.order, payment=payment, received_by=received_by
        )

    @staticmethod
    def _positive_int(value, fallback):
        try:
            parsed = int(value or fallback)
        except (TypeError, ValueError):
            return fallback
        return parsed if parsed > 0 else fallback

    @staticmethod
    def _marta_pid(*, payment):
        pid = int(payment.id.int % JAVA_LONG_MAX)
        return pid or 1

    @classmethod
    def _normalize_marta_debug_payload(cls, value):
        if isinstance(value, list):
            return [cls._normalize_marta_debug_payload(item) for item in value]
        if not isinstance(value, dict):
            return value

        normalized = {}
        for key, item in value.items():
            normalized[key] = cls._normalize_marta_debug_payload(item)
        if "http_status" in normalized and "httpStatus" not in normalized:
            normalized["httpStatus"] = normalized["http_status"]
        return normalized
