from decimal import ROUND_HALF_UP, Decimal

from django.db.models import Sum
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from rest_framework.exceptions import ValidationError

from apps.billing.helpers import get_payment_model
from apps.catalog.utils.cash_sale import is_catalog_item_cash_sale_forbidden

Payment = get_payment_model()


class OrderPaymentPolicyMixin:
    _TOTAL_OVERRIDE_UPDATE_FIELDS = [
        "total",
        "total_override",
        "total_override_reason",
        "total_overridden_by",
        "total_overridden_at",
        "updated_at",
    ]

    def _apply_total_override(
        self, *, order, final_total, reason, overridden_by, save=True
    ):
        if final_total is None:
            return False
        if (
            getattr(order.restaurant, "payment_total_mode", "fixed")
            != "cashier_editable"
        ):
            raise ValidationError(
                {
                    "finalTotal": _(
                        "This restaurant does not allow cashier-edited totals."
                    )
                }
            )
        if order.payments.filter(status=Payment.Status.SUCCEEDED).exists():
            raise ValidationError(
                {
                    "finalTotal": _(
                        "The total cannot be changed after a successful payment."
                    )
                }
            )

        final_total = int(final_total)
        calculated_total = int(order.calculated_total or order.total or 0)
        if final_total == calculated_total:
            order.total = calculated_total
            order.total_override = None
            order.total_override_reason = ""
            order.total_overridden_by = None
            order.total_overridden_at = None
        else:
            order.total = final_total
            order.total_override = final_total
            order.total_override_reason = ""
            order.total_overridden_by = overridden_by
            order.total_overridden_at = timezone.now()
        if save:
            self._save_total_override(order=order)
        return True

    def _save_total_override(self, *, order):
        order.save(update_fields=self._TOTAL_OVERRIDE_UPDATE_FIELDS)

    def _validate_shift(self, *, order, cash_shift):
        if cash_shift is None:
            raise ValidationError(
                {"detail": _("Open a cashier shift before accepting payments.")}
            )
        if cash_shift.status != cash_shift.Status.OPEN:
            raise ValidationError(
                {"detail": _("Only an open cashier shift can be used for payment.")}
            )
        if cash_shift.cash_desk.restaurant_id != order.restaurant_id:
            raise ValidationError(
                {"detail": _("Active cashier shift belongs to another restaurant.")}
            )

    def _validate_payment_amount(self, *, order, amount):
        remaining_amount = self._remaining_amount(order=order)
        if remaining_amount <= 0:
            raise ValidationError({"amount": _("Order is already fully paid.")})
        if amount > remaining_amount:
            raise ValidationError(
                {"amount": _("Payment amount cannot exceed the remaining total.")}
            )

    def _apply_fiscal_breakdown(
        self, *, order, payment, amount=None, cash_amount=None, card_amount=None
    ):
        amount = int(amount if amount is not None else payment.amount or 0)
        cash_amount = int(
            cash_amount if cash_amount is not None else payment.cash_amount or 0
        )
        card_amount = int(
            card_amount if card_amount is not None else payment.card_amount or 0
        )
        restricted_total = self._restricted_fiscal_total(order=order)
        fiscal_card_amount = min(max(card_amount, restricted_total), amount)
        fiscal_cash_amount = max(amount - fiscal_card_amount, 0)
        adjustment_reason = (
            "cash_forbidden_category"
            if restricted_total
            and (fiscal_cash_amount != cash_amount or fiscal_card_amount != card_amount)
            else ""
        )
        payment.fiscal_cash_amount = fiscal_cash_amount
        payment.fiscal_card_amount = fiscal_card_amount
        payment.fiscal_adjustment_reason = adjustment_reason
        payment.save(
            update_fields=[
                "fiscal_cash_amount",
                "fiscal_card_amount",
                "fiscal_adjustment_reason",
                "updated_at",
            ]
        )

    @staticmethod
    def _remaining_amount(*, order) -> int:
        paid_total = (
            order.payments.filter(status=Payment.Status.SUCCEEDED)
            .aggregate(total=Sum("amount"))
            .get("total")
            or 0
        )
        return max(0, int(order.total or 0) - int(paid_total or 0))

    @staticmethod
    def _succeeded_payment_totals(*, order) -> dict:
        return order.payments.filter(status=Payment.Status.SUCCEEDED).aggregate(
            amount=Sum("amount"),
            cash_amount=Sum("cash_amount"),
            card_amount=Sum("card_amount"),
        )

    def _restricted_fiscal_total(self, *, order) -> int:
        order_item_model = order.items.model
        order_items = list(
            order.items.exclude(status=order_item_model.Status.CANCELLED)
            .select_related("catalog_item", "catalog_item__category")
            .order_by("created_at", "id")
        )
        restricted_items = [
            item for item in order_items if is_catalog_item_cash_sale_forbidden(item)
        ]
        if not restricted_items:
            return 0
        restricted_total = sum(int(item.line_total or 0) for item in restricted_items)
        service_fee = max(int(order.calculated_total or 0) - int(order.subtotal or 0), 0)
        if service_fee <= 0:
            return restricted_total
        subtotal = sum(int(item.line_total or 0) for item in order_items)
        if subtotal <= 0:
            return restricted_total + service_fee
        restricted_fee = int(
            (
                Decimal(service_fee) * Decimal(restricted_total) / Decimal(subtotal)
            ).quantize(
                Decimal("1"),
                rounding=ROUND_HALF_UP,
            )
        )
        return restricted_total + restricted_fee
