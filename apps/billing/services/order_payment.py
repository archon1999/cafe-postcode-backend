import logging

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from rest_framework.exceptions import ValidationError
from rest_framework.exceptions import APIException

from apps.billing.helpers import get_payment_model
from apps.billing.services.cash_shift import CashShiftService
from apps.integrations.services import charge_payment, issue_fiscal_receipts
from apps.sales.helpers import get_order_model
from apps.sales.services import (
    OrderStateService,
    OrderSubmissionService,
    validate_order_markings,
)
from common.api.permissions import (
    POS_FISCAL_RECEIPTS_SKIP_PERMISSION,
    has_permission_code,
)

from .edge_payment_results import EdgePaymentResultsMixin
from .marta_payment_flow import MartaPaymentFlowMixin
from .order_payment_completion import OrderPaymentCompletionMixin
from .order_payment_policy import OrderPaymentPolicyMixin

logger = logging.getLogger(__name__)
Order = get_order_model()
Payment = get_payment_model()


class ServiceFeeQuoteStale(APIException):
    status_code = 409
    default_code = "SERVICE_FEE_QUOTE_STALE"
    default_detail = "Service fee quote is stale. Refresh the order and confirm the payment again."


class OrderPaymentService(
    OrderPaymentCompletionMixin,
    OrderPaymentPolicyMixin,
    EdgePaymentResultsMixin,
    MartaPaymentFlowMixin,
):
    order_submission_service_class = OrderSubmissionService
    state_service_class = OrderStateService
    shift_service_class = CashShiftService

    @staticmethod
    def _prepare_service_fee_quote(
        *,
        order,
        quote,
        trusted_edge_replay,
        trusted_frozen_at=None,
    ):
        if not order.has_hourly_service_fee or order.service_fee_frozen_at is not None:
            order.recalculate_totals(preserve_override=True)
            return order.service_fee_frozen_at

        quote_at = trusted_frozen_at if trusted_edge_replay and trusted_frozen_at else timezone.now()
        current = {
            "quotedAt": quote_at.isoformat(),
            "billableMinutes": order.get_service_fee_billable_minutes(as_of=quote_at),
            "serviceFee": order.get_service_fee_amount(as_of=quote_at),
            "calculatedTotal": order.get_calculated_total(as_of=quote_at),
        }
        if not trusted_edge_replay:
            quote = quote if isinstance(quote, dict) else {}
            def quote_int(*names):
                for name in names:
                    if name in quote and quote[name] is not None:
                        try:
                            return int(quote[name])
                        except (TypeError, ValueError):
                            return -1
                return -1

            expected = {
                "billableMinutes": quote_int("billableMinutes", "billable_minutes"),
                "serviceFee": quote_int("serviceFee", "service_fee"),
                "calculatedTotal": quote_int("calculatedTotal", "calculated_total"),
            }
            if expected != {key: current[key] for key in expected}:
                raise ServiceFeeQuoteStale(
                    detail={
                        "code": "SERVICE_FEE_QUOTE_STALE",
                        "detail": ServiceFeeQuoteStale.default_detail,
                        "currentQuote": current,
                    }
                )

        order.recalculate_totals(preserve_override=True, as_of=quote_at)
        return quote_at

    @transaction.atomic
    def process(
        self,
        *,
        order: Order,
        payload: dict,
        received_by,
        cash_shift=None,
        trusted_edge_replay=False,
        occurred_at=None,
    ):
        from apps.billing.serializers import PaymentSerializer

        order = (
            Order.objects.select_for_update(of=("self",))
            .select_related(
                "restaurant",
                "table_session__hall",
                "table_session__table",
            )
            .get(pk=order.pk)
        )
        if cash_shift is not None:
            cash_shift = (
                type(cash_shift).objects.select_for_update(of=("self",))
                .select_related(
                    "cash_desk",
                    "cash_desk__payment_integration",
                    "cash_desk__printer_integration",
                    "cash_desk__fiscal_integration",
                )
                .get(pk=cash_shift.pk)
            )

        edge_operation_id = str(
            payload.get("edge_operation_id") or payload.get("edgeOperationId") or ""
        ).strip()
        if edge_operation_id:
            existing = (
                Payment.objects.filter(edge_operation_id=edge_operation_id)
                .select_related("order")
                .first()
            )
            if existing is not None:
                if existing.order_id != order.id:
                    raise ValidationError(
                        {"edgeOperationId": _("Operation ID belongs to another order.")}
                    )
                receipts = list(existing.receipts.order_by("created_at"))
                return {
                    "payment": existing,
                    "receipt": receipts[0] if receipts else None,
                    "receipts": receipts,
                    "order": existing.order,
                    "detail": (existing.provider_payload or {}).get("detail", ""),
                }

        edge_payment_id = payload.pop('edge_payment_id', payload.pop('edgePaymentId', None))
        if edge_payment_id is not None and not trusted_edge_replay:
            raise ValidationError({'edgePaymentId': 'Only a trusted Local Agent may set payment identity.'})

        state_service = self.state_service_class()
        state_service.ensure_order_can_be_paid(order=order)
        state_service.ensure_delivery_details(order=order)
        if self._should_submit_before_payment(order=order):
            self.order_submission_service_class().submit(order)

        self._validate_shift(order=order, cash_shift=cash_shift, trusted_edge_replay=trusted_edge_replay)
        serializer = PaymentSerializer(data=payload)
        serializer.is_valid(raise_exception=True)
        service_fee_quote = serializer.validated_data.pop("service_fee_quote", None)
        service_fee_frozen_at = serializer.validated_data.pop("service_fee_frozen_at", None)
        if service_fee_frozen_at is not None and not trusted_edge_replay:
            raise ValidationError(
                {"serviceFeeFrozenAt": _("Only a trusted local agent may freeze service-fee time.")}
            )
        service_fee_quote_at = self._prepare_service_fee_quote(
            order=order,
            quote=service_fee_quote,
            trusted_edge_replay=trusted_edge_replay,
            trusted_frozen_at=service_fee_frozen_at,
        )
        manual_card_override = bool(
            serializer.validated_data.pop("manual_card_override", False)
        )
        manual_card_reason = str(
            serializer.validated_data.pop("manual_card_reason", "") or ""
        )
        edge_provider_result = serializer.validated_data.pop(
            "edge_provider_result", None
        )
        edge_fiscal_results = serializer.validated_data.pop("edge_fiscal_results", None)
        edge_fiscal_results_json = serializer.validated_data.pop(
            "edge_fiscal_results_json", None
        )
        final_total = serializer.validated_data.pop("final_total", None)
        total_override_reason = serializer.validated_data.pop(
            "total_override_reason", ""
        )
        total_override_prepared = self._apply_total_override(
            order=order,
            final_total=final_total,
            reason=total_override_reason,
            overridden_by=received_by,
            save=False,
        )
        if edge_provider_result is not None and not trusted_edge_replay:
            raise ValidationError(
                {
                    "edgeProviderResult": _(
                        "Only a trusted local agent may replay a terminal result."
                    )
                }
            )
        if (
            edge_fiscal_results is not None or edge_fiscal_results_json is not None
        ) and not trusted_edge_replay:
            raise ValidationError(
                {
                    "edgeFiscalResults": _(
                        "Only a trusted local agent may submit fiscal results."
                    )
                }
            )
        if edge_fiscal_results_json is not None:
            if edge_fiscal_results is not None:
                raise ValidationError(
                    {
                        "edgeFiscalResults": _(
                            "Submit fiscal results in only one format."
                        )
                    }
                )
            edge_fiscal_results = self._parse_edge_fiscal_results_json(
                edge_fiscal_results_json
            )
        register_fiscal = bool(serializer.validated_data.get("register_fiscal", True))
        partial_payment = int(serializer.validated_data['amount']) < self._remaining_amount(order=order)
        if register_fiscal and not edge_fiscal_results and not partial_payment:
            from .financial_authority import FinancialAgentRequired
            raise FinancialAgentRequired()
        if partial_payment and edge_fiscal_results:
            raise ValidationError({'code': 'PARTIAL_PAYMENT_FISCAL_EVIDENCE', 'detail': 'Partial payments require explicit receipt allocation before projection.'})
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
        cash_desk = (
            cash_shift.cash_desk
            if cash_shift is not None
            else order.restaurant.cash_desks.filter(is_active=True)
            .order_by("name")
            .first()
        )
        validated_edge_fiscal_results = (
            self._validated_edge_fiscal_results(
                results=edge_fiscal_results,
                cash_desk=cash_desk,
                register_fiscal=register_fiscal,
                expected_amount=int(order.total or 0),
            )
            if edge_fiscal_results
            else None
        )
        if cash_desk and serializer.validated_data["method"] not in set(
            cash_desk.enabled_payment_methods or []
        ):
            raise ValidationError(
                {
                    "method": _(
                        "Selected payment method is disabled on the active cash desk."
                    )
                }
            )
        if cash_desk and serializer.validated_data["method"] == Payment.Method.MIXED:
            enabled_methods = set(cash_desk.enabled_payment_methods or [])
            if not {Payment.Method.CASH, Payment.Method.CARD}.issubset(enabled_methods):
                raise ValidationError(
                    {
                        "method": _(
                            "Mixed payment requires cash and card methods on the active cash desk."
                        )
                    }
                )

        payment_amount = serializer.validated_data["amount"]
        self._validate_payment_amount(order=order, amount=payment_amount)
        validated_edge_result = None
        if (serializer.validated_data['method'] in {Payment.Method.CARD, Payment.Method.MIXED}
                and edge_provider_result is None and not (manual_card_override and serializer.validated_data['method'] == Payment.Method.CARD)):
            raise ValidationError({'code': 'EDGE_PROVIDER_RESULT_REQUIRED', 'detail': 'A confirmed owner terminal outcome is required before projecting a card payment.'})
        if edge_provider_result is not None:
            validated_edge_result = self._validated_edge_provider_result(
                result=edge_provider_result,
                method=serializer.validated_data["method"],
                card_amount=serializer.validated_data["card_amount"],
                edge_operation_id=edge_operation_id,
            )
        if total_override_prepared:
            self._save_total_override(order=order)
        payment = serializer.save(
            **({'id': edge_payment_id} if edge_payment_id else {}),
            order=order,
            received_by=received_by,
            cash_shift=cash_shift,
            cash_desk=cash_desk,
            origin_cash_shift_id=cash_shift.pk,
            occurred_at=occurred_at if trusted_edge_replay else None,
            financial_snapshot={
                'orderTotal': int(order.total), 'subtotal': int(order.subtotal),
                'fiscalRequested': register_fiscal, 'partialPayment': partial_payment,
                'cashShiftId': str(cash_shift.pk), 'cashierId': str(received_by.pk),
                'occurredAt': occurred_at.isoformat() if occurred_at else None,
                'items': [{'id': str(item.pk), 'catalogItemId': str(item.catalog_item_id),
                           'quantity': str(item.quantity), 'unitPrice': int(item.unit_price),
                           'lineTotal': int(item.line_total), 'status': item.status}
                          for item in order.items.all()],
            },
        )

        payment_result = (
            validated_edge_result
            if validated_edge_result is not None
            else charge_payment(
                order=order,
                payment=payment,
                manual_card_override=manual_card_override,
                manual_card_reason=manual_card_reason,
            )
        )
        payment.status = (
            Payment.Status.SUCCEEDED
            if payment_result.get("ok")
            else Payment.Status.FAILED
        )
        payment.external_ref = payment_result.get("reference", "")
        payment.provider_payload = payment_result
        payment.paid_at = (
            (occurred_at or timezone.now()) if payment.status == Payment.Status.SUCCEEDED else None
        )
        payment.save(
            update_fields=[
                "status",
                "external_ref",
                "provider_payload",
                "paid_at",
                "updated_at",
            ]
        )

        if payment.status == Payment.Status.FAILED:
            logger.warning(
                "Payment charge failed",
                extra={
                    "order_id": str(order.pk),
                    "payment_id": str(payment.pk),
                    "method": payment.method,
                },
            )
            return {
                "payment": payment,
                "receipt": None,
                "order": order,
                "detail": payment_result.get("detail")
                or payment_result.get("message")
                or _("Payment charge failed."),
            }

        return self._complete_successful_payment(
            order=order,
            payment=payment,
            received_by=received_by,
            fiscal_results=validated_edge_fiscal_results,
            service_fee_quote_at=service_fee_quote_at,
        )


from .payment_fiscal_retry import PaymentFiscalRetryService
