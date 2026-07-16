from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.core.exceptions import ObjectDoesNotExist
from rest_framework.exceptions import ValidationError

from apps.billing.helpers import get_cash_shift_model
from apps.integrations.services import (
    close_fiscal_shift as close_fiscal_shift,
    get_fiscal_device_status,
    get_fiscal_shift_report as get_fiscal_shift_report,
    open_fiscal_shift as open_fiscal_shift,
)
from apps.restaurants.helpers import get_cash_desk_model
from apps.users.models import EmployeeProfile, User
from common.api.permissions import POS_CASH_SHIFT_MANAGE_PERMISSION, has_permission_code

from .cash_shift_reporting import CashShiftReportingMixin
from .fiscal_shift_lifecycle import FiscalShiftLifecycleMixin

CashDesk = get_cash_desk_model()
CashShift = get_cash_shift_model()


class CashShiftService(CashShiftReportingMixin, FiscalShiftLifecycleMixin):
    cashier_role_codes = ("cashier", "fast_food_cashier")

    def get_active_shift(self, *, restaurant, user):
        return (
            CashShift.objects.select_related(
                "cash_desk",
                "cash_desk__payment_integration",
                "cash_desk__printer_integration",
                "cash_desk__fiscal_integration",
                "opened_by",
                "cashier",
            )
            .filter(cash_desk__restaurant=restaurant, status=CashShift.Status.OPEN)
            .filter(Q(cashier=user) | Q(cashier__isnull=True))
            .order_by("-opened_at")
            .first()
        )

    def get_available_cash_desks(self, *, restaurant):
        return list(
            CashDesk.objects.select_related(
                "payment_integration", "printer_integration", "fiscal_integration"
            )
            .filter(restaurant=restaurant, is_active=True)
            .order_by("name")
        )

    def get_available_cashiers(self, *, restaurant):
        return list(
            User.objects.filter(
                restaurant_profile__restaurant=restaurant,
                role__code__in=self.cashier_role_codes,
                is_active=True,
            )
            .exclude(
                employee_profile__employment_status__in=(
                    EmployeeProfile.EmploymentStatus.INACTIVE,
                    EmployeeProfile.EmploymentStatus.ARCHIVED,
                )
            )
            .select_related("role", "employee_profile")
            .order_by("full_name", "username")
            .distinct()
        )

    def get_active_shifts_for_manager(self, *, restaurant, user):
        if not has_permission_code(user, POS_CASH_SHIFT_MANAGE_PERMISSION):
            return []
        return list(
            CashShift.objects.select_related(
                "cash_desk",
                "cash_desk__payment_integration",
                "cash_desk__printer_integration",
                "opened_by",
                "cashier",
            )
            .filter(cash_desk__restaurant=restaurant, status=CashShift.Status.OPEN)
            .order_by("cash_desk__name", "opened_at")
        )

    def get_active_shift_for_cash_desk(self, *, restaurant, cash_desk=None, user=None):
        queryset = CashShift.objects.select_related(
            "cash_desk",
            "cash_desk__payment_integration",
            "cash_desk__printer_integration",
            "opened_by",
            "cashier",
        ).filter(
            cash_desk__restaurant=restaurant,
            status=CashShift.Status.OPEN,
        )
        if cash_desk is not None:
            queryset = queryset.filter(cash_desk=cash_desk)
        if user is not None:
            queryset = queryset.filter(Q(cashier=user) | Q(cashier__isnull=True))
        return queryset.order_by("-opened_at").first()

    def build_context(self, *, restaurant, user):
        active_shift = self.get_active_shift(restaurant=restaurant, user=user)
        available_cash_desks = self.get_available_cash_desks(restaurant=restaurant)
        status_cash_desk = (
            active_shift.cash_desk
            if active_shift is not None
            else available_cash_desks[0]
            if available_cash_desks
            else None
        )
        return {
            "restaurant_fiscal_profile": {
                "legal_name": restaurant.legal_name,
                "tax_number": restaurant.tax_number,
                "phone": restaurant.phone,
                "social": restaurant.social,
                "address": restaurant.address,
                "service_fee_enabled": bool(
                    getattr(restaurant, "service_fee_enabled", False)
                ),
                "service_fee_percent": getattr(restaurant, "service_fee_percent", 0)
                or 0,
                "vat_enabled": bool(getattr(restaurant, "vat_enabled", False)),
                "vat_percent": getattr(restaurant, "vat_percent", 0) or 0,
            },
            "available_cash_desks": available_cash_desks,
            "available_cashiers": self.get_available_cashiers(restaurant=restaurant),
            "current_shift": active_shift,
            "active_shifts": self.get_active_shifts_for_manager(
                restaurant=restaurant, user=user
            ),
            "fiscal_shift_open": self.has_open_fiscal_shift(restaurant=restaurant),
            "fiscal_device_status": get_fiscal_device_status(
                restaurant=restaurant, cash_desk=status_cash_desk
            ),
        }

    def open_shift(
        self,
        *,
        restaurant=None,
        branch=None,
        cash_desk,
        opened_by,
        cashier=None,
        opening_cash_amount=0,
        notes_open="",
    ):
        restaurant = restaurant or branch
        if restaurant is None:
            raise ValueError("restaurant is required")
        if cash_desk.restaurant_id != restaurant.id:
            raise ValidationError(
                {
                    "cashDeskId": "Selected cash desk does not belong to the current restaurant."
                }
            )
        if not cash_desk.is_active:
            raise ValidationError({"cashDeskId": "Selected cash desk is inactive."})
        if cashier is not None:
            if not self._is_valid_cashier(restaurant=restaurant, cashier=cashier):
                raise ValidationError({"cashierId": "Selected cashier was not found."})
            if CashShift.objects.filter(
                cash_desk__restaurant=restaurant,
                cashier=cashier,
                status=CashShift.Status.OPEN,
            ).exists():
                raise ValidationError(
                    {"cashierId": "Selected cashier already has an active shift."}
                )
        elif len(self.get_available_cash_desks(restaurant=restaurant)) > 1:
            raise ValidationError(
                {
                    "cashierId": "Cashier selection is required when more than one cash desk is active."
                }
            )
        if CashShift.objects.filter(
            cash_desk=cash_desk, status=CashShift.Status.OPEN
        ).exists():
            raise ValidationError(
                {"cashDeskId": "Selected cash desk already has an active shift."}
            )

        with transaction.atomic():
            if (
                cashier is not None
                and CashShift.objects.filter(
                    cash_desk__restaurant=restaurant,
                    cashier=cashier,
                    status=CashShift.Status.OPEN,
                ).exists()
            ):
                raise ValidationError(
                    {"cashierId": "Selected cashier already has an active shift."}
                )
            if CashShift.objects.filter(
                cash_desk=cash_desk, status=CashShift.Status.OPEN
            ).exists():
                raise ValidationError(
                    {"cashDeskId": "Selected cash desk already has an active shift."}
                )

            shift = CashShift.objects.create(
                cash_desk=cash_desk,
                cashier=cashier,
                opened_by=opened_by,
                opened_at=timezone.now(),
                opening_cash_amount=max(0, opening_cash_amount or 0),
                notes_open=notes_open or "",
            )
        return shift

    def _is_valid_cashier(self, *, restaurant, cashier):
        if not cashier or not cashier.is_active:
            return False
        if getattr(cashier.role, "code", None) not in self.cashier_role_codes:
            return False
        if getattr(cashier.get_restaurant_scope(), "id", None) != restaurant.id:
            return False
        try:
            employee_profile = cashier.employee_profile
        except ObjectDoesNotExist:
            employee_profile = None
        if (
            employee_profile is not None
            and employee_profile.employment_status
            != EmployeeProfile.EmploymentStatus.ACTIVE
        ):
            return False
        return True

    @transaction.atomic
    def close_shift(
        self, *, shift, actual_closing_cash_amount, closed_by, notes_close=""
    ):
        if shift.status != CashShift.Status.OPEN:
            raise ValidationError({"detail": "Only open shifts can be closed."})

        self.ensure_no_unresolved_fiscal_payments(shift=shift)
        snapshot = self.build_shift_snapshot(shift=shift)
        expected = snapshot["expected_closing_cash_amount"]
        actual = (
            expected
            if actual_closing_cash_amount is None
            else max(0, actual_closing_cash_amount or 0)
        )
        shift.status = CashShift.Status.CLOSED
        shift.closed_by = closed_by
        shift.closed_at = timezone.now()
        shift.actual_closing_cash_amount = actual
        shift.expected_closing_cash_amount = expected
        shift.cash_difference_amount = actual - expected
        shift.cash_total = snapshot["cash_total"]
        shift.card_total = snapshot["card_total"]
        shift.qr_total = snapshot["qr_total"]
        shift.refund_total = snapshot["refund_total"]
        shift.receipt_count = snapshot["receipt_count"]
        shift.reprint_count = snapshot["reprint_count"]
        shift.notes_close = notes_close or ""
        shift.close_report_payload = {
            "snapshot": snapshot,
            "report": self.build_fiscal_shift_report(shift=shift),
            "closed_at": shift.closed_at.isoformat() if shift.closed_at else None,
        }
        shift.save(
            update_fields=[
                "status",
                "closed_by",
                "closed_at",
                "actual_closing_cash_amount",
                "expected_closing_cash_amount",
                "cash_difference_amount",
                "cash_total",
                "card_total",
                "qr_total",
                "refund_total",
                "receipt_count",
                "reprint_count",
                "close_report_payload",
                "notes_close",
                "updated_at",
            ]
        )
        return shift
