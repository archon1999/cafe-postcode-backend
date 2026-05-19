from django.db import transaction
from django.db.models import Count, Exists, OuterRef, Q, Sum
from django.utils import timezone
from django.core.exceptions import ObjectDoesNotExist
from rest_framework.exceptions import ValidationError

from apps.billing.helpers import (
    get_cash_shift_model,
    get_fiscal_shift_session_model,
    get_payment_model,
    get_payment_refund_model,
    get_receipt_model,
)
from apps.integrations.services import close_fiscal_shift, open_fiscal_shift
from apps.restaurants.helpers import get_cash_desk_model
from apps.users.models import EmployeeProfile, User
from common.api.permissions import POS_CASH_SHIFT_MANAGE_PERMISSION, has_permission_code

CashDesk = get_cash_desk_model()
CashShift = get_cash_shift_model()
FiscalShiftSession = get_fiscal_shift_session_model()
Payment = get_payment_model()
PaymentRefund = get_payment_refund_model()
Receipt = get_receipt_model()


class CashShiftService:
    cashier_role_codes = ('cashier', 'fast_food_cashier')

    def get_active_shift(self, *, restaurant, user):
        return (
            CashShift.objects.select_related('cash_desk', 'cash_desk__payment_integration', 'opened_by', 'cashier')
            .filter(cash_desk__restaurant=restaurant, status=CashShift.Status.OPEN)
            .filter(Q(cashier=user) | Q(cashier__isnull=True))
            .order_by('-opened_at')
            .first()
        )

    def get_available_cash_desks(self, *, restaurant):
        return list(
            CashDesk.objects.select_related('payment_integration')
            .filter(restaurant=restaurant, is_active=True)
            .order_by('name')
        )

    def get_available_cashiers(self, *, restaurant):
        return list(
            User.objects.filter(
                restaurant_profile__restaurant=restaurant,
                role__code__in=self.cashier_role_codes,
                is_active=True,
            )
            .exclude(employee_profile__employment_status__in=(
                EmployeeProfile.EmploymentStatus.INACTIVE,
                EmployeeProfile.EmploymentStatus.ARCHIVED,
            ))
            .select_related('role', 'employee_profile')
            .order_by('full_name', 'username')
            .distinct()
        )

    def get_active_shifts_for_manager(self, *, restaurant, user):
        if not has_permission_code(user, POS_CASH_SHIFT_MANAGE_PERMISSION):
            return []
        return list(
            CashShift.objects.select_related('cash_desk', 'cash_desk__payment_integration', 'opened_by', 'cashier')
            .filter(cash_desk__restaurant=restaurant, status=CashShift.Status.OPEN)
            .order_by('cash_desk__name', 'opened_at')
        )

    def get_active_shift_for_cash_desk(self, *, restaurant, cash_desk=None, user=None):
        queryset = CashShift.objects.select_related('cash_desk', 'cash_desk__payment_integration', 'opened_by', 'cashier').filter(
            cash_desk__restaurant=restaurant,
            status=CashShift.Status.OPEN,
        )
        if cash_desk is not None:
            queryset = queryset.filter(cash_desk=cash_desk)
        if user is not None:
            queryset = queryset.filter(Q(cashier=user) | Q(cashier__isnull=True))
        return queryset.order_by('-opened_at').first()

    def build_context(self, *, restaurant, user):
        active_shift = self.get_active_shift(restaurant=restaurant, user=user)
        return {
            'restaurant_fiscal_profile': {
                'legal_name': restaurant.legal_name,
                'tax_number': restaurant.tax_number,
                'vat_enabled': bool(getattr(restaurant, 'vat_enabled', False)),
                'vat_percent': getattr(restaurant, 'vat_percent', 0) or 0,
            },
            'available_cash_desks': self.get_available_cash_desks(restaurant=restaurant),
            'available_cashiers': self.get_available_cashiers(restaurant=restaurant),
            'current_shift': active_shift,
            'active_shifts': self.get_active_shifts_for_manager(restaurant=restaurant, user=user),
        }

    def _payment_scope_queryset(self, *, shift=None, shifts=None, restaurant=None, cash_desk=None, paid_at_from=None, paid_at_to=None):
        payments = Payment.objects.filter(status=Payment.Status.SUCCEEDED)
        if shift is not None:
            payments = payments.filter(cash_shift=shift)
        if shifts is not None:
            payments = payments.filter(cash_shift__in=shifts)
        if restaurant is not None:
            payments = payments.filter(order__restaurant=restaurant)
        if cash_desk is not None:
            payments = payments.filter(cash_desk=cash_desk)
        if paid_at_from is not None:
            payments = payments.filter(paid_at__gte=paid_at_from)
        if paid_at_to is not None:
            payments = payments.filter(paid_at__lte=paid_at_to)
        return payments

    def get_unresolved_fiscal_payments_queryset(
        self,
        *,
        shift=None,
        shifts=None,
        restaurant=None,
        cash_desk=None,
        paid_at_from=None,
        paid_at_to=None,
    ):
        receipt_queryset = Receipt.objects.filter(payment_id=OuterRef('pk'), kind=Receipt.Kind.FISCAL)
        return (
            self._payment_scope_queryset(
                shift=shift,
                shifts=shifts,
                restaurant=restaurant,
                cash_desk=cash_desk,
                paid_at_from=paid_at_from,
                paid_at_to=paid_at_to,
            )
            .filter(register_fiscal=True)
            .annotate(
                has_fiscal_receipt=Exists(receipt_queryset),
                has_sent_fiscal_receipt=Exists(receipt_queryset.filter(status=Receipt.Status.SENT)),
                has_failed_fiscal_receipt=Exists(receipt_queryset.filter(status=Receipt.Status.FAILED)),
            )
            .filter(
                Q(has_fiscal_receipt=False)
                | Q(has_sent_fiscal_receipt=False)
                | Q(has_failed_fiscal_receipt=True)
            )
        )

    def ensure_no_unresolved_fiscal_payments(self, **filters):
        unresolved = self.get_unresolved_fiscal_payments_queryset(**filters)
        count = unresolved.count()
        if count:
            raise ValidationError({
                'detail': (
                    'Fiscalga yuborilmagan yoki xato bo‘lgan cheklar bor. '
                    'Smenani yopishdan oldin ularni "Yopilmagan hisoblar" bo‘limidan qayta yuboring.'
                ),
                'unresolved_fiscal_count': count,
            })

    def build_fiscal_shift_report(
        self,
        *,
        shift=None,
        shifts=None,
        restaurant=None,
        cash_desk=None,
        paid_at_from=None,
        paid_at_to=None,
    ):
        payments = (
            self._payment_scope_queryset(
                shift=shift,
                shifts=shifts,
                restaurant=restaurant,
                cash_desk=cash_desk,
                paid_at_from=paid_at_from,
                paid_at_to=paid_at_to,
            )
            .select_related('order', 'received_by')
            .prefetch_related('receipts')
            .order_by('paid_at', 'created_at')
        )
        all_rows = []
        fiscal_rows = []
        for payment in payments:
            sent_receipts = [
                receipt
                for receipt in payment.receipts.all()
                if receipt.kind == Receipt.Kind.FISCAL and receipt.status == Receipt.Status.SENT
            ]
            row = {
                'payment_id': str(payment.id),
                'order_id': str(payment.order_id),
                'order_number': payment.order.order_number if payment.order_id else None,
                'method': payment.method,
                'amount': payment.amount,
                'paid_at': payment.paid_at,
                'cashier_name': payment.received_by.full_name if payment.received_by_id else '',
                'fiscal_receipt_count': len(sent_receipts),
            }
            all_rows.append(row)
            if sent_receipts:
                fiscal_rows.append(row)

        def summary(rows):
            totals = {}
            for row in rows:
                totals[row['method']] = totals.get(row['method'], 0) + int(row['amount'] or 0)
            return {'count': len(rows), 'total': sum(totals.values()), 'totals_by_method': totals, 'rows': rows}

        return {'all': summary(all_rows), 'fiscal_sent': summary(fiscal_rows)}

    def open_fiscal_shift(self, *, restaurant, cash_desk=None, opened_by=None):
        existing = FiscalShiftSession.objects.filter(
            restaurant=restaurant,
            cash_desk=cash_desk,
            status=FiscalShiftSession.Status.OPEN,
        ).first()
        if existing is not None:
            raise ValidationError({'detail': 'Fiscal smena allaqachon ochiq.'})

        result = open_fiscal_shift(restaurant=restaurant, cash_desk=cash_desk)
        FiscalShiftSession.objects.create(
            restaurant=restaurant,
            cash_desk=cash_desk,
            opened_by=opened_by,
            status=FiscalShiftSession.Status.OPEN,
            provider=str(result.get('provider') or ''),
            terminal_id=self._terminal_id_from_fiscal_result(result),
            opened_at=timezone.now(),
            open_payload=result,
        )
        return result

    def ensure_fiscal_shift_open(self, *, restaurant, cash_desk=None, opened_by=None):
        existing = self._get_active_fiscal_session(restaurant=restaurant, cash_desk=cash_desk)
        if existing is not None:
            return None
        try:
            return self.open_fiscal_shift(restaurant=restaurant, cash_desk=cash_desk, opened_by=opened_by)
        except ValueError as error:
            detail = str(error)
            if 'not configured' in detail or 'Unsupported fiscal provider' in detail:
                return None
            raise

    def close_fiscal_shift(self, *, restaurant, cash_desk=None, closed_by=None):
        session = self._get_active_fiscal_session(restaurant=restaurant, cash_desk=cash_desk)
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
        result = close_fiscal_shift(restaurant=restaurant, cash_desk=cash_desk)
        if session is not None:
            session.status = FiscalShiftSession.Status.CLOSED
            session.closed_by = closed_by
            session.closed_at = timezone.now()
            session.close_payload = result
            if not session.provider:
                session.provider = str(result.get('provider') or '')
            if not session.terminal_id:
                session.terminal_id = self._terminal_id_from_fiscal_result(result)
            session.save(
                update_fields=[
                    'status',
                    'closed_by',
                    'closed_at',
                    'close_payload',
                    'provider',
                    'terminal_id',
                    'updated_at',
                ]
            )
        return {'result': result, 'report': report}

    def _get_active_fiscal_session(self, *, restaurant, cash_desk=None):
        return (
            FiscalShiftSession.objects.filter(
                restaurant=restaurant,
                cash_desk=cash_desk,
                status=FiscalShiftSession.Status.OPEN,
            )
            .order_by('-opened_at')
            .first()
        )

    @staticmethod
    def _terminal_id_from_fiscal_result(result):
        response = result.get('response') if isinstance(result, dict) else {}
        if not isinstance(response, dict):
            response = {}
        return str(response.get('TerminalID') or response.get('Fiscal') or result.get('terminal_id') or '').strip()

    @transaction.atomic
    def open_shift(self, *, restaurant=None, branch=None, cash_desk, opened_by, cashier=None, opening_cash_amount=0, notes_open=''):
        restaurant = restaurant or branch
        if restaurant is None:
            raise ValueError('restaurant is required')
        if cash_desk.restaurant_id != restaurant.id:
            raise ValidationError({'cashDeskId': 'Selected cash desk does not belong to the current restaurant.'})
        if not cash_desk.is_active:
            raise ValidationError({'cashDeskId': 'Selected cash desk is inactive.'})
        if cashier is not None:
            if not self._is_valid_cashier(restaurant=restaurant, cashier=cashier):
                raise ValidationError({'cashierId': 'Selected cashier was not found.'})
            if CashShift.objects.filter(cash_desk__restaurant=restaurant, cashier=cashier, status=CashShift.Status.OPEN).exists():
                raise ValidationError({'cashierId': 'Selected cashier already has an active shift.'})
        elif len(self.get_available_cash_desks(restaurant=restaurant)) > 1:
            raise ValidationError({'cashierId': 'Cashier selection is required when more than one cash desk is active.'})
        if CashShift.objects.filter(cash_desk=cash_desk, status=CashShift.Status.OPEN).exists():
            raise ValidationError({'cashDeskId': 'Selected cash desk already has an active shift.'})

        shift = CashShift.objects.create(
            cash_desk=cash_desk,
            cashier=cashier,
            opened_by=opened_by,
            opened_at=timezone.now(),
            opening_cash_amount=max(0, opening_cash_amount or 0),
            notes_open=notes_open or '',
        )
        self.ensure_fiscal_shift_open(restaurant=restaurant, opened_by=opened_by)
        return shift

    def _is_valid_cashier(self, *, restaurant, cashier):
        if not cashier or not cashier.is_active:
            return False
        if getattr(cashier.role, 'code', None) not in self.cashier_role_codes:
            return False
        if getattr(cashier.get_restaurant_scope(), 'id', None) != restaurant.id:
            return False
        try:
            employee_profile = cashier.employee_profile
        except ObjectDoesNotExist:
            employee_profile = None
        if employee_profile is not None and employee_profile.employment_status != EmployeeProfile.EmploymentStatus.ACTIVE:
            return False
        return True

    def build_shift_snapshot(self, *, shift):
        payments = shift.payments.filter(status=Payment.Status.SUCCEEDED)
        refunds = PaymentRefund.objects.filter(payment__cash_shift=shift, status=PaymentRefund.Status.SUCCEEDED)
        receipts = Receipt.objects.filter(payment__cash_shift=shift)

        payment_totals = payments.values('method').annotate(total=Sum('amount'))
        totals = {item['method']: item['total'] or 0 for item in payment_totals}

        refund_total = refunds.aggregate(total=Sum('amount')).get('total') or 0
        cash_refund_total = (
            refunds.filter(payment__method=Payment.Method.CASH).aggregate(total=Sum('amount')).get('total') or 0
        )

        return {
            'cash_total': totals.get(Payment.Method.CASH, 0),
            'card_total': totals.get(Payment.Method.CARD, 0),
            'qr_total': totals.get(Payment.Method.QR, 0),
            'refund_total': refund_total,
            'receipt_count': receipts.filter(kind=Receipt.Kind.FISCAL).aggregate(total=Count('id')).get('total') or 0,
            'reprint_count': receipts.aggregate(total=Sum('reprint_count')).get('total') or 0,
            'expected_closing_cash_amount': (shift.opening_cash_amount or 0)
            + totals.get(Payment.Method.CASH, 0)
            - cash_refund_total,
        }

    @transaction.atomic
    def close_shift(self, *, shift, actual_closing_cash_amount, closed_by, notes_close=''):
        if shift.status != CashShift.Status.OPEN:
            raise ValidationError({'detail': 'Only open shifts can be closed.'})

        self.ensure_no_unresolved_fiscal_payments(shift=shift)
        snapshot = self.build_shift_snapshot(shift=shift)
        actual = max(0, actual_closing_cash_amount or 0)
        expected = snapshot['expected_closing_cash_amount']
        shift.status = CashShift.Status.CLOSED
        shift.closed_by = closed_by
        shift.closed_at = timezone.now()
        shift.actual_closing_cash_amount = actual
        shift.expected_closing_cash_amount = expected
        shift.cash_difference_amount = actual - expected
        shift.cash_total = snapshot['cash_total']
        shift.card_total = snapshot['card_total']
        shift.qr_total = snapshot['qr_total']
        shift.refund_total = snapshot['refund_total']
        shift.receipt_count = snapshot['receipt_count']
        shift.reprint_count = snapshot['reprint_count']
        shift.notes_close = notes_close or ''
        shift.save(
            update_fields=[
                'status',
                'closed_by',
                'closed_at',
                'actual_closing_cash_amount',
                'expected_closing_cash_amount',
                'cash_difference_amount',
                'cash_total',
                'card_total',
                'qr_total',
                'refund_total',
                'receipt_count',
                'reprint_count',
                'notes_close',
                'updated_at',
            ]
        )
        return shift
