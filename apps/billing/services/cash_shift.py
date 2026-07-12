from decimal import Decimal, ROUND_HALF_UP

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
from apps.integrations.services import close_fiscal_shift, get_fiscal_device_status, open_fiscal_shift
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
            CashShift.objects.select_related(
                'cash_desk',
                'cash_desk__payment_integration',
                'cash_desk__printer_integration',
                'cash_desk__fiscal_integration',
                'opened_by',
                'cashier',
            )
            .filter(cash_desk__restaurant=restaurant, status=CashShift.Status.OPEN)
            .filter(Q(cashier=user) | Q(cashier__isnull=True))
            .order_by('-opened_at')
            .first()
        )

    def get_available_cash_desks(self, *, restaurant):
        return list(
            CashDesk.objects.select_related('payment_integration', 'printer_integration', 'fiscal_integration')
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
            CashShift.objects.select_related(
                'cash_desk',
                'cash_desk__payment_integration',
                'cash_desk__printer_integration',
                'opened_by',
                'cashier',
            )
            .filter(cash_desk__restaurant=restaurant, status=CashShift.Status.OPEN)
            .order_by('cash_desk__name', 'opened_at')
        )

    def get_active_shift_for_cash_desk(self, *, restaurant, cash_desk=None, user=None):
        queryset = CashShift.objects.select_related(
            'cash_desk',
            'cash_desk__payment_integration',
            'cash_desk__printer_integration',
            'opened_by',
            'cashier',
        ).filter(
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
        available_cash_desks = self.get_available_cash_desks(restaurant=restaurant)
        status_cash_desk = active_shift.cash_desk if active_shift is not None else available_cash_desks[0] if available_cash_desks else None
        return {
            'restaurant_fiscal_profile': {
                'legal_name': restaurant.legal_name,
                'tax_number': restaurant.tax_number,
                'phone': restaurant.phone,
                'social': restaurant.social,
                'address': restaurant.address,
                'service_fee_enabled': bool(getattr(restaurant, 'service_fee_enabled', False)),
                'service_fee_percent': getattr(restaurant, 'service_fee_percent', 0) or 0,
                'vat_enabled': bool(getattr(restaurant, 'vat_enabled', False)),
                'vat_percent': getattr(restaurant, 'vat_percent', 0) or 0,
            },
            'available_cash_desks': available_cash_desks,
            'available_cashiers': self.get_available_cashiers(restaurant=restaurant),
            'current_shift': active_shift,
            'active_shifts': self.get_active_shifts_for_manager(restaurant=restaurant, user=user),
            'fiscal_shift_open': self.has_open_fiscal_shift(restaurant=restaurant),
            'fiscal_device_status': get_fiscal_device_status(restaurant=restaurant, cash_desk=status_cash_desk),
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
                'amount': int(payment.amount or 0),
                'cash_amount': int(getattr(payment, 'cash_amount', 0) or 0),
                'card_amount': int(getattr(payment, 'card_amount', 0) or 0),
                'qr_amount': int(payment.amount or 0) if payment.method == Payment.Method.QR else 0,
                'paid_at': payment.paid_at.isoformat() if payment.paid_at else None,
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

        payment_ids = [payment.id for payment in payments]
        fiscal_payment_ids = [row['payment_id'] for row in fiscal_rows]
        refunds = list(
            PaymentRefund.objects.filter(payment_id__in=payment_ids, status=PaymentRefund.Status.SUCCEEDED)
            .select_related('payment')
            .order_by('refunded_at', 'created_at')
        )
        fiscal_refunds = [refund for refund in refunds if str(refund.payment_id) in set(fiscal_payment_ids)]
        terminal_id = self._report_terminal_id(cash_desk=cash_desk, payments=payments)
        opened_at = paid_at_from or (shift.opened_at if shift is not None else None)
        closed_at = paid_at_to or timezone.now()
        all_report = self._build_unikassa_like_report(
            source='pos',
            title='POS smena hisoboti',
            rows=all_rows,
            refunds=refunds,
            opened_at=opened_at,
            closed_at=closed_at,
            terminal_id=terminal_id,
            restaurant=restaurant or getattr(getattr(shift, 'cash_desk', None), 'restaurant', None),
        )
        fiscal_sent_report = self._build_unikassa_like_report(
            source='pos_fiscal_sent',
            title='Fiscalga yuborilgan POS hisoboti',
            rows=fiscal_rows,
            refunds=fiscal_refunds,
            opened_at=opened_at,
            closed_at=closed_at,
            terminal_id=terminal_id,
            restaurant=restaurant or getattr(getattr(shift, 'cash_desk', None), 'restaurant', None),
        )

        return {
            'all': summary(all_rows),
            'fiscal_sent': summary(fiscal_rows),
            'pos_report': all_report,
            'fiscal_sent_report': fiscal_sent_report,
        }

    def _build_unikassa_like_report(
        self,
        *,
        source: str,
        title: str,
        rows: list[dict],
        refunds: list,
        opened_at,
        closed_at,
        terminal_id: str,
        restaurant=None,
    ) -> dict:
        sale_totals = self._totals_by_method(rows)
        sale_tender_totals = self._tender_totals(rows)
        refund_totals = self._refund_tender_totals(refunds)
        sale_total = sum(sale_totals.values())
        refund_total = sum(refund_totals.values())
        fiscal_receipt_count = sum(int(row.get('fiscal_receipt_count') or 0) for row in rows)
        return {
            'ReportSource': source,
            'ReportTitle': title,
            'TerminalID': terminal_id,
            'OpenTime': self._format_report_datetime(opened_at),
            'CloseTime': self._format_report_datetime(closed_at),
            'TotalSaleCount': len(rows),
            'TotalRefundCount': len(refunds),
            'TotalCash': {
                'Sale': sale_tender_totals.get(Payment.Method.CASH, 0),
                'Refund': refund_totals.get(Payment.Method.CASH, 0),
            },
            'TotalCard': {
                'Sale': sale_tender_totals.get(Payment.Method.CARD, 0),
                'Refund': refund_totals.get(Payment.Method.CARD, 0),
            },
            'TotalQR': {
                'Sale': sale_tender_totals.get(Payment.Method.QR, 0),
                'Refund': refund_totals.get(Payment.Method.QR, 0),
            },
            'TotalVAT': {'Sale': self._estimate_vat(sale_total, restaurant=restaurant), 'Refund': self._estimate_vat(refund_total, restaurant=restaurant)},
            'TotalSaleAmount': sale_total,
            'TotalRefundAmount': refund_total,
            'NetTotal': sale_total - refund_total,
            'OrdersCount': len({row.get('order_id') for row in rows if row.get('order_id')}),
            'PaymentsCount': len(rows),
            'FiscalReceiptCount': fiscal_receipt_count,
            'Payments': rows,
        }

    @staticmethod
    def _totals_by_method(rows: list[dict]) -> dict:
        totals = {}
        for row in rows:
            method = row.get('method') or ''
            totals[method] = totals.get(method, 0) + int(row.get('amount') or 0)
        return totals

    @staticmethod
    def _refund_totals_by_method(refunds: list) -> dict:
        totals = {}
        for refund in refunds:
            method = getattr(getattr(refund, 'payment', None), 'method', '') or ''
            totals[method] = totals.get(method, 0) + int(refund.amount or 0)
        return totals

    @staticmethod
    def _tender_totals(rows: list[dict]) -> dict:
        totals = {}
        for row in rows:
            totals[Payment.Method.CASH] = totals.get(Payment.Method.CASH, 0) + int(row.get('cash_amount') or 0)
            totals[Payment.Method.CARD] = totals.get(Payment.Method.CARD, 0) + int(row.get('card_amount') or 0)
            totals[Payment.Method.QR] = totals.get(Payment.Method.QR, 0) + int(row.get('qr_amount') or 0)
        return totals

    @staticmethod
    def _refund_tender_totals(refunds: list) -> dict:
        totals = {}
        for refund in refunds:
            for method, amount in CashShiftService._refund_tender_amounts(refund).items():
                totals[method] = totals.get(method, 0) + amount
        return totals

    @staticmethod
    def _refund_tender_amounts(refund) -> dict:
        payment = getattr(refund, 'payment', None)
        refund_amount = int(getattr(refund, 'amount', 0) or 0)
        if payment is None or refund_amount <= 0:
            return {}
        if payment.method == Payment.Method.QR:
            return {Payment.Method.QR: refund_amount}

        payment_amount = int(getattr(payment, 'amount', 0) or 0)
        cash_amount = int(getattr(payment, 'cash_amount', 0) or 0)
        card_amount = int(getattr(payment, 'card_amount', 0) or 0)
        if cash_amount > 0 and card_amount > 0 and payment_amount > 0:
            cash_refund = int(
                (Decimal(refund_amount) * Decimal(cash_amount) / Decimal(payment_amount)).quantize(
                    Decimal('1'),
                    rounding=ROUND_HALF_UP,
                )
            )
            cash_refund = min(max(cash_refund, 0), refund_amount)
            return {
                Payment.Method.CASH: cash_refund,
                Payment.Method.CARD: refund_amount - cash_refund,
            }
        if cash_amount > 0:
            return {Payment.Method.CASH: refund_amount}
        if card_amount > 0:
            return {Payment.Method.CARD: refund_amount}
        if payment.method == Payment.Method.CASH:
            return {Payment.Method.CASH: refund_amount}
        return {Payment.Method.CARD: refund_amount}

    @staticmethod
    def _format_report_datetime(value) -> str | None:
        if value is None:
            return None
        return timezone.localtime(value).replace(microsecond=0).strftime('%Y-%m-%d %H:%M:%S')

    @staticmethod
    def _estimate_vat(amount: int, *, restaurant=None) -> int:
        if not restaurant or not getattr(restaurant, 'vat_enabled', False):
            return 0
        try:
            percent = Decimal(str(getattr(restaurant, 'vat_percent', 0) or 0))
        except Exception:
            return 0
        if percent <= 0:
            return 0
        return int((Decimal(amount) * percent / (Decimal('100') + percent)).quantize(Decimal('1'), rounding=ROUND_HALF_UP))

    @staticmethod
    def _report_terminal_id(*, cash_desk=None, payments=None) -> str:
        if cash_desk is not None and getattr(cash_desk, 'terminal_id', ''):
            return str(cash_desk.terminal_id).strip()
        payments = list(payments or [])
        for payment in payments:
            payment_cash_desk = getattr(payment, 'cash_desk', None)
            if payment_cash_desk is not None and getattr(payment_cash_desk, 'terminal_id', ''):
                return str(payment_cash_desk.terminal_id).strip()
        return ''

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

    def has_open_fiscal_shift(self, *, restaurant, cash_desk=None):
        return self._get_active_fiscal_session(restaurant=restaurant, cash_desk=cash_desk) is not None

    def close_fiscal_shift(self, *, restaurant, cash_desk=None, closed_by=None):
        session = self._get_active_fiscal_session(restaurant=restaurant, cash_desk=cash_desk)
        if session is None:
            return {
                'skipped': True,
                'reason': 'fiscal_shift_not_open',
                'detail': 'Fiscal smena ochilmagan.',
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
        result = close_fiscal_shift(restaurant=restaurant, cash_desk=cash_desk)
        if session is not None:
            close_payload = {
                'provider_result': result,
                'reports': report,
                'closed_at': timezone.now().isoformat(),
            }
            session.status = FiscalShiftSession.Status.CLOSED
            session.closed_by = closed_by
            session.closed_at = timezone.now()
            session.close_payload = close_payload
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
        return {
            'result': result,
            'provider_report': result.get('provider_report') if isinstance(result, dict) else None,
            'report': report,
            'reports': report,
        }

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
        provider_report = result.get('provider_report') if isinstance(result, dict) else {}
        z_info = provider_report.get('z_info') if isinstance(provider_report, dict) else {}
        if not isinstance(z_info, dict):
            z_info = {}
        return str(response.get('TerminalID') or response.get('Fiscal') or result.get('terminal_id') or z_info.get('TerminalID') or '').strip()

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

        with transaction.atomic():
            if cashier is not None and CashShift.objects.filter(
                cash_desk__restaurant=restaurant,
                cashier=cashier,
                status=CashShift.Status.OPEN,
            ).exists():
                raise ValidationError({'cashierId': 'Selected cashier already has an active shift.'})
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

        totals = payments.aggregate(
            cash_total=Sum('cash_amount'),
            card_total=Sum('card_amount'),
            qr_total=Sum('amount', filter=Q(method=Payment.Method.QR)),
        )

        refund_total = refunds.aggregate(total=Sum('amount')).get('total') or 0
        cash_refund_total = sum(
            self._refund_tender_amounts(refund).get(Payment.Method.CASH, 0)
            for refund in refunds.select_related('payment')
        )

        return {
            'cash_total': totals.get('cash_total') or 0,
            'card_total': totals.get('card_total') or 0,
            'qr_total': totals.get('qr_total') or 0,
            'refund_total': refund_total,
            'receipt_count': receipts.filter(kind=Receipt.Kind.FISCAL).aggregate(total=Count('id')).get('total') or 0,
            'reprint_count': receipts.aggregate(total=Sum('reprint_count')).get('total') or 0,
            'expected_closing_cash_amount': (shift.opening_cash_amount or 0)
            + (totals.get('cash_total') or 0)
            - cash_refund_total,
        }

    @transaction.atomic
    def close_shift(self, *, shift, actual_closing_cash_amount, closed_by, notes_close=''):
        if shift.status != CashShift.Status.OPEN:
            raise ValidationError({'detail': 'Only open shifts can be closed.'})

        self.ensure_no_unresolved_fiscal_payments(shift=shift)
        snapshot = self.build_shift_snapshot(shift=shift)
        expected = snapshot['expected_closing_cash_amount']
        actual = expected if actual_closing_cash_amount is None else max(0, actual_closing_cash_amount or 0)
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
        shift.close_report_payload = {
            'snapshot': snapshot,
            'report': self.build_fiscal_shift_report(shift=shift),
            'closed_at': shift.closed_at.isoformat() if shift.closed_at else None,
        }
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
                'close_report_payload',
                'notes_close',
                'updated_at',
            ]
        )
        return shift
