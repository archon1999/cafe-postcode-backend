"""Payroll calculations and state changes. Money stays in UZS decimal units."""

import hashlib
import json
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal, ROUND_HALF_UP

from django.db import models, transaction
from django.db.models import Prefetch
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.billing.models import Payment, PaymentRefund
from apps.sales.models import Order, OrderItem
from apps.users.models import User
from apps.workforce.models import Timesheet

from .models import CompensationRate, KpiRule, PayrollAdjustment, PayrollPayout, PayrollPeriod, PayrollRun


CENT = Decimal('0.01')
NEGATIVE_KINDS = {
    PayrollAdjustment.Kind.ADVANCE,
    PayrollAdjustment.Kind.PENALTY,
    PayrollAdjustment.Kind.DEDUCTION,
    PayrollAdjustment.Kind.CORRECTION_DEBIT,
}


def money(value):
    return Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)


def valid_employee(*, restaurant, employee_id):
    employee = User.objects.filter(pk=employee_id, restaurant_profile__restaurant=restaurant).first()
    if employee is None:
        raise ValidationError({'employeeId': 'Employee is not in this restaurant.'})
    return employee


def valid_period(*, restaurant, period_id, for_update=False):
    queryset = PayrollPeriod.objects.filter(pk=period_id, restaurant=restaurant)
    if for_update:
        queryset = queryset.select_for_update()
    period = queryset.first()
    if period is None:
        raise ValidationError({'periodId': 'Payroll period was not found.'})
    return period


@transaction.atomic
def create_period(*, restaurant, label, start_date, end_date):
    from apps.restaurants.models import Restaurant

    if end_date < start_date:
        raise ValidationError({'endDate': 'End date must be on or after start date.'})
    Restaurant.objects.select_for_update().get(pk=restaurant.pk)
    if PayrollPeriod.objects.filter(
        restaurant=restaurant, start_date__lte=end_date, end_date__gte=start_date
    ).exists():
        raise ValidationError({'startDate': 'Payroll periods cannot overlap.'})
    return PayrollPeriod.objects.create(
        restaurant=restaurant, label=label.strip() or start_date.strftime('%Y-%m'),
        start_date=start_date, end_date=end_date,
    )


@transaction.atomic
def create_rate(*, restaurant, employee_id, rate_type, amount, effective_from, actor):
    employee = valid_employee(restaurant=restaurant, employee_id=employee_id)
    if rate_type not in CompensationRate.Type.values:
        raise ValidationError({'rateType': 'Unknown compensation type.'})
    amount = money(amount)
    if amount <= 0:
        raise ValidationError({'amount': 'Amount must be positive.'})
    if CompensationRate.objects.filter(restaurant=restaurant, employee=employee, effective_from=effective_from).exists():
        raise ValidationError({'effectiveFrom': 'A rate already starts on this date.'})
    return CompensationRate.objects.create(
        restaurant=restaurant, employee=employee, rate_type=rate_type,
        amount=amount, effective_from=effective_from, created_by=actor,
    )


@transaction.atomic
def create_kpi_rule(*, restaurant, role_id, percent, effective_from, actor):
    from apps.users.models import Role

    role = None
    if role_id:
        role = Role.objects.filter(pk=role_id).first()
        if role is None:
            raise ValidationError({'roleId': 'Role was not found.'})
    percent = Decimal(str(percent))
    if percent < 0 or percent > 100:
        raise ValidationError({'percent': 'Percent must be between 0 and 100.'})
    if KpiRule.objects.filter(restaurant=restaurant, role=role, effective_from=effective_from).exists():
        raise ValidationError({'effectiveFrom': 'A rule already starts on this date.'})
    return KpiRule.objects.create(
        restaurant=restaurant, role=role, percent=percent,
        effective_from=effective_from, created_by=actor,
    )


@transaction.atomic
def create_adjustment(*, restaurant, period_id, employee_id, kind, amount, reason, actor,
                      payment_method=None, disbursed_at=None):
    period = valid_period(restaurant=restaurant, period_id=period_id, for_update=True)
    employee = valid_employee(restaurant=restaurant, employee_id=employee_id)
    if kind not in PayrollAdjustment.Kind.values:
        raise ValidationError({'kind': 'Unknown adjustment type.'})
    amount = money(amount)
    if amount <= 0:
        raise ValidationError({'amount': 'Amount must be positive.'})
    if not reason.strip():
        raise ValidationError({'reason': 'A reason is required.'})
    evidence = {}
    if kind == PayrollAdjustment.Kind.ADVANCE:
        if payment_method not in PayrollPayout.Method.values:
            raise ValidationError({'paymentMethod': 'Manual advance payment method is required.'})
        if disbursed_at is None or disbursed_at > timezone.now() + timedelta(minutes=5):
            raise ValidationError({'disbursedAt': 'A past advance disbursement time is required.'})
        evidence = {'paymentMethod': payment_method, 'disbursedAt': disbursed_at.isoformat()}
    return PayrollAdjustment.objects.create(
        restaurant=restaurant, period=period, employee=employee, kind=kind,
        amount=amount, reason=reason.strip(), evidence=evidence, created_by=actor,
    )


@transaction.atomic
def decide_adjustment(*, restaurant, adjustment_id, actor, approve):
    adjustment = PayrollAdjustment.objects.select_for_update().filter(
        pk=adjustment_id, restaurant=restaurant
    ).first()
    if adjustment is None:
        raise ValidationError({'adjustmentId': 'Adjustment was not found.'})
    if adjustment.status != PayrollAdjustment.Status.PENDING:
        raise ValidationError({'status': 'Adjustment has already been decided.'})
    if approve and adjustment.origin == PayrollAdjustment.Origin.POS and PayrollAdjustment.objects.filter(
        period=adjustment.period, employee=adjustment.employee,
        origin=PayrollAdjustment.Origin.POS, status=PayrollAdjustment.Status.APPROVED,
    ).exists():
        raise ValidationError({'status': 'POS KPI has already been approved for this period.'})
    adjustment.status = PayrollAdjustment.Status.APPROVED if approve else PayrollAdjustment.Status.REJECTED
    adjustment.approved_by = actor
    adjustment.approved_at = timezone.now()
    adjustment.save(update_fields=['status', 'approved_by', 'approved_at', 'updated_at'])
    return adjustment


def _rate_for_date(rates, day):
    return next((row for row in rates if row.effective_from <= day), None)


def _base_lines(*, restaurant, period, employee):
    rates = list(CompensationRate.objects.filter(
        restaurant=restaurant, employee=employee, effective_from__lte=period.end_date
    ).order_by('-effective_from', '-created_at'))
    if not rates:
        raise ValidationError({'rate': f'No compensation rate for {employee.full_name}.'})
    timesheets = list(Timesheet.objects.filter(
        restaurant=restaurant, employee=employee, status=Timesheet.Status.APPROVED,
        work_date__gte=period.start_date, work_date__lte=period.end_date,
    ).order_by('work_date', 'pk'))
    grouped = defaultdict(lambda: {'amount': Decimal('0'), 'quantity': Decimal('0'), 'timesheetIds': []})
    # A monthly rate is a fixed base for the entire payroll period, regardless
    # of attendance or how many calendar days the period contains. Day weights
    # are used only to blend an effective-dated rate change inside the period.
    period_days = Decimal((period.end_date - period.start_date).days + 1)
    day = period.start_date
    while day <= period.end_date:
        rate = _rate_for_date(rates, day)
        if rate is None and rates[-1].rate_type == CompensationRate.Type.MONTHLY:
            rate = rates[-1]
        if rate is None:
            day += timedelta(days=1)
            continue
        if rate.rate_type == CompensationRate.Type.MONTHLY:
            bucket = grouped[str(rate.pk)]
            bucket['rate'] = rate
            bucket['quantity'] += Decimal('1') / period_days
            bucket['amount'] += rate.amount / period_days
        day += timedelta(days=1)
    for row in timesheets:
        rate = _rate_for_date(rates, row.work_date)
        if rate is None:
            raise ValidationError({'rate': f'Missing compensation rate on {row.work_date.isoformat()}.'})
        if rate.rate_type == CompensationRate.Type.MONTHLY:
            continue
        quantity = (
            Decimal(row.approved_minutes) / Decimal('60')
            if rate.rate_type == CompensationRate.Type.HOURLY
            else Decimal(row.approved_shift_count)
        )
        bucket = grouped[str(rate.pk)]
        bucket['rate'] = rate
        bucket['quantity'] += quantity
        bucket['amount'] += rate.amount * quantity
        bucket['timesheetIds'].append(str(row.pk))
        bucket.setdefault('timesheets', []).append({
            'id': str(row.pk), 'workDate': row.work_date.isoformat(),
            'approvedMinutes': row.approved_minutes,
            'approvedShiftCount': row.approved_shift_count,
        })
    lines = []
    for bucket in sorted(grouped.values(), key=lambda row: row['rate'].effective_from):
        rate = bucket['rate']
        amount = money(bucket['amount'])
        if amount == 0:
            continue
        lines.append({
            'kind': f'base_{rate.rate_type}', 'label': f'{rate.get_rate_type_display()} base',
            'amount': str(amount), 'quantity': str(bucket['quantity'].quantize(Decimal('0.001'))),
            'unit': {'hourly': 'hour', 'daily': 'shift', 'monthly': 'period'}[rate.rate_type],
            'rate': str(rate.amount), 'rateId': str(rate.pk),
            'effectiveFrom': rate.effective_from.isoformat(),
            'timesheetIds': bucket['timesheetIds'],
            'timesheets': bucket.get('timesheets', []),
        })
    return lines


def _adjustment_lines(*, restaurant, period, employee):
    rows = PayrollAdjustment.objects.filter(
        restaurant=restaurant, period=period, employee=employee,
        status=PayrollAdjustment.Status.APPROVED,
    ).order_by('created_at', 'pk')
    return [{
        'kind': row.kind, 'label': row.reason,
        'amount': str(-row.amount if row.kind in NEGATIVE_KINDS else row.amount),
        'adjustmentId': str(row.pk), 'origin': row.origin,
    } for row in rows]


@transaction.atomic
def build_run(*, restaurant, period_id, employee_id, actor):
    period = valid_period(restaurant=restaurant, period_id=period_id, for_update=True)
    employee = valid_employee(restaurant=restaurant, employee_id=employee_id)
    lines = _base_lines(restaurant=restaurant, period=period, employee=employee)
    lines += _adjustment_lines(restaurant=restaurant, period=period, employee=employee)
    total = money(sum((Decimal(line['amount']) for line in lines), Decimal('0')))
    signature = hashlib.sha256(json.dumps(lines, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    latest = PayrollRun.objects.select_for_update().filter(period=period, employee=employee).order_by('-version').first()
    if latest and latest.source_signature == signature:
        return latest
    if latest and latest.status == PayrollRun.Status.DRAFT:
        latest.lines = lines
        latest.total = total
        latest.source_signature = signature
        latest.built_by = actor
        latest.save(update_fields=['lines', 'total', 'source_signature', 'built_by', 'updated_at'])
        return latest
    return PayrollRun.objects.create(
        restaurant=restaurant, period=period, employee=employee,
        version=latest.version + 1 if latest else 1, lines=lines,
        source_signature=signature, total=total, built_by=actor,
    )


def build_all_runs(*, restaurant, period_id, actor, employee_id=None):
    period = valid_period(restaurant=restaurant, period_id=period_id)
    if employee_id:
        return [build_run(restaurant=restaurant, period_id=period.pk, employee_id=employee_id, actor=actor)]
    employee_ids = set(CompensationRate.objects.filter(
        restaurant=restaurant, effective_from__lte=period.end_date
    ).values_list('employee_id', flat=True))
    employee_ids.update(Timesheet.objects.filter(
        restaurant=restaurant, status=Timesheet.Status.APPROVED,
        work_date__gte=period.start_date, work_date__lte=period.end_date,
    ).values_list('employee_id', flat=True))
    employee_ids.update(PayrollAdjustment.objects.filter(
        restaurant=restaurant, period=period, status=PayrollAdjustment.Status.APPROVED,
    ).values_list('employee_id', flat=True))
    return [build_run(restaurant=restaurant, period_id=period.pk, employee_id=eid, actor=actor)
            for eid in sorted(employee_ids, key=str)]


@transaction.atomic
def lock_runs(*, restaurant, period_id, actor):
    period = valid_period(restaurant=restaurant, period_id=period_id, for_update=True)
    if Timesheet.objects.filter(
        restaurant=restaurant, work_date__gte=period.start_date,
        work_date__lte=period.end_date, status=Timesheet.Status.DRAFT,
    ).exists():
        raise ValidationError({'timesheets': 'Resolve draft timesheets before locking payroll.'})
    if PayrollAdjustment.objects.filter(
        restaurant=restaurant, period=period, status=PayrollAdjustment.Status.PENDING,
    ).exists():
        raise ValidationError({'adjustments': 'Decide pending adjustments before locking payroll.'})
    # Before the first lock, a manager must approve the current POS result. A
    # refund that arrives after approval must not silently carry the old KPI
    # amount into the finalized calculation. Once locked, revisions require an
    # explicit manual correction rather than changing the historical POS line.
    if period.status == PayrollPeriod.Status.OPEN:
        pos_adjustments = PayrollAdjustment.objects.filter(
            restaurant=restaurant, period=period,
            origin=PayrollAdjustment.Origin.POS,
            status=PayrollAdjustment.Status.APPROVED,
        )
        for adjustment in pos_adjustments:
            try:
                current = kpi_preview(
                    restaurant=restaurant, period_id=period.pk,
                    employee_id=adjustment.employee_id,
                )
            except ValidationError as exc:
                raise ValidationError({
                    'kpi': f'POS KPI for {adjustment.employee.full_name} must be reviewed again.'
                }) from exc
            if not _same_pos_kpi(adjustment.evidence, current):
                raise ValidationError({
                    'kpi': f'POS KPI for {adjustment.employee.full_name} changed; review and approve it again.'
                })
    # Rebuild against the current approved sources immediately before freezing.
    build_all_runs(restaurant=restaurant, period_id=period.pk, actor=actor)
    latest_ids = {}
    for run in PayrollRun.objects.filter(period=period).order_by('employee_id', '-version'):
        latest_ids.setdefault(run.employee_id, run.pk)
    if not latest_ids:
        raise ValidationError({'runs': 'Build payroll runs before locking.'})
    latest = list(PayrollRun.objects.select_for_update().filter(pk__in=latest_ids.values()))
    for run in latest:
        if run.total < 0:
            raise ValidationError({
                'adjustments': f'Payroll total for {run.employee.full_name} cannot be negative; review approved deductions.',
            })
        if paid_amount(period=period, employee=run.employee) > run.total:
            raise ValidationError({
                'payouts': f'Existing manual payouts exceed the new total for {run.employee.full_name}.',
            })
    now = timezone.now()
    for run in latest:
        if run.status == PayrollRun.Status.DRAFT:
            run.status = PayrollRun.Status.LOCKED
            run.locked_by = actor
            run.locked_at = now
            run.save(update_fields=['status', 'locked_by', 'locked_at', 'updated_at'])
    period.status = PayrollPeriod.Status.LOCKED
    period.locked_by = actor
    period.locked_at = now
    period.save(update_fields=['status', 'locked_by', 'locked_at', 'updated_at'])
    return latest


def latest_run(*, period, employee):
    return PayrollRun.objects.filter(period=period, employee=employee).order_by('-version').first()


def paid_amount(*, period, employee):
    return money(sum((row.amount for row in PayrollPayout.objects.filter(
        period=period, employee=employee, voided_at__isnull=True
    )), Decimal('0')))


@transaction.atomic
def record_payout(*, restaurant, period_id, employee_id, amount, method, paid_at, note, actor):
    period = valid_period(restaurant=restaurant, period_id=period_id, for_update=True)
    employee = valid_employee(restaurant=restaurant, employee_id=employee_id)
    run = latest_run(period=period, employee=employee)
    if run is None or run.status != PayrollRun.Status.LOCKED:
        raise ValidationError({'run': 'The latest payroll calculation must be locked.'})
    amount = money(amount)
    if amount <= 0:
        raise ValidationError({'amount': 'Amount must be positive.'})
    if method not in PayrollPayout.Method.values:
        raise ValidationError({'method': 'Unknown manual payment method.'})
    remaining = run.total - paid_amount(period=period, employee=employee)
    if amount > remaining:
        raise ValidationError({'amount': 'Payment exceeds remaining payroll balance.'})
    if paid_at > timezone.now() + timedelta(minutes=5):
        raise ValidationError({'paidAt': 'Payment date cannot be in the future.'})
    return PayrollPayout.objects.create(
        restaurant=restaurant, period=period, employee=employee,
        amount=amount, method=method, paid_at=paid_at,
        note=note.strip(), recorded_by=actor,
    )


@transaction.atomic
def void_payout(*, restaurant, payout_id, reason, actor):
    payout = PayrollPayout.objects.select_for_update().filter(
        pk=payout_id, restaurant=restaurant
    ).first()
    if payout is None:
        raise ValidationError({'payoutId': 'Payment record was not found.'})
    if payout.voided_at:
        raise ValidationError({'payoutId': 'Payment record is already voided.'})
    if not reason.strip():
        raise ValidationError({'reason': 'A reason is required.'})
    payout.voided_at = timezone.now()
    payout.voided_by = actor
    payout.void_reason = reason.strip()
    payout.save(update_fields=['voided_at', 'voided_by', 'void_reason', 'updated_at'])
    return payout


def _period_window(period):
    tz = timezone.get_current_timezone()
    return (
        timezone.make_aware(datetime.combine(period.start_date, time.min), tz),
        timezone.make_aware(datetime.combine(period.end_date + timedelta(days=1), time.min), tz),
    )


def _kpi_rule(*, restaurant, employee, period):
    rules = KpiRule.objects.filter(
        restaurant=restaurant, effective_from__lte=period.end_date,
    ).filter(models.Q(role=employee.role) | models.Q(role__isnull=True)).order_by('-effective_from')
    role_rule = next((rule for rule in rules if rule.role_id == employee.role_id and rule.role_id), None)
    return role_rule or next((rule for rule in rules if rule.role_id is None), None)


def kpi_preview(*, restaurant, period_id, employee_id):
    period = valid_period(restaurant=restaurant, period_id=period_id)
    employee = valid_employee(restaurant=restaurant, employee_id=employee_id)
    rule = _kpi_rule(restaurant=restaurant, employee=employee, period=period)
    if rule is None:
        raise ValidationError({'kpiRule': 'No POS KPI rule applies to this employee.'})
    start, end = _period_window(period)
    payments = Payment.objects.filter(status=Payment.Status.SUCCEEDED).prefetch_related(
        Prefetch('refunds', queryset=PaymentRefund.objects.filter(status=PaymentRefund.Status.SUCCEEDED))
    )
    orders = Order.objects.filter(
        restaurant=restaurant, status=Order.Status.CLOSED,
        closed_at__gte=start, closed_at__lt=end,
    ).prefetch_related(
        Prefetch('items', queryset=OrderItem.objects.exclude(status=OrderItem.Status.CANCELLED)),
        Prefetch('payments', queryset=payments),
    )
    net_sales = Decimal('0')
    order_count = 0
    for order in orders:
        items = list(order.items.all())
        gross = sum((Decimal(item.line_total) for item in items), Decimal('0'))
        if gross <= 0:
            continue
        paid = sum((Decimal(payment.amount) for payment in order.payments.all()), Decimal('0'))
        refunded = sum((Decimal(refund.amount) for payment in order.payments.all()
                        for refund in payment.refunds.all()), Decimal('0'))
        # A settled check can contain a separate service fee. Allocate its
        # discount/refund to merchandise by the merchandise share of the
        # original calculated check, then cap at the actual item value.
        calculated = Decimal(order.calculated_total or 0)
        check_basis = max(calculated, gross)
        allocatable = min(max(paid - refunded, Decimal('0')) * gross / check_basis, gross)
        if allocatable <= 0:
            continue
        attributed = sum((Decimal(item.line_total) for item in items if item.created_by_id == employee.pk), Decimal('0'))
        if attributed > 0:
            net_sales += allocatable * attributed / gross
            order_count += 1
    net_sales = money(net_sales)
    amount = money(net_sales * rule.percent / Decimal('100'))
    return {
        'employeeId': str(employee.pk), 'employeeName': employee.full_name,
        'periodId': str(period.pk), 'ruleId': str(rule.pk),
        'percent': str(rule.percent), 'netSales': str(net_sales),
        'amount': str(amount), 'orderCount': order_count,
    }


def _same_pos_kpi(previous, current):
    return all(previous.get(key) == current.get(key) for key in (
        'employeeId', 'periodId', 'ruleId', 'percent',
        'netSales', 'amount', 'orderCount',
    ))


@transaction.atomic
def approve_pos_kpi(*, restaurant, period_id, employee_id, actor):
    period = valid_period(restaurant=restaurant, period_id=period_id, for_update=True)
    if period.status == PayrollPeriod.Status.LOCKED:
        raise ValidationError({'kpi': 'Locked payroll requires an explicit correction for new POS sales or refunds.'})
    employee = valid_employee(restaurant=restaurant, employee_id=employee_id)
    existing = PayrollAdjustment.objects.select_for_update().filter(
        period=period, employee=employee, origin=PayrollAdjustment.Origin.POS,
        status=PayrollAdjustment.Status.APPROVED,
    ).first()
    preview = kpi_preview(restaurant=restaurant, period_id=period.pk, employee_id=employee.pk)
    amount = money(preview['amount'])
    if existing:
        if _same_pos_kpi(existing.evidence, preview):
            raise ValidationError({'kpi': 'POS KPI has already been approved for this period.'})
        existing.status = PayrollAdjustment.Status.SUPERSEDED
        existing.save(update_fields=['status', 'updated_at'])
        if amount <= 0:
            return existing
    elif amount <= 0:
        raise ValidationError({'kpi': 'There is no positive POS KPI to approve.'})
    return PayrollAdjustment.objects.create(
        restaurant=restaurant, period=period, employee=employee,
        kind=PayrollAdjustment.Kind.KPI, origin=PayrollAdjustment.Origin.POS,
        amount=amount, reason='POS sales KPI', evidence=preview,
        status=PayrollAdjustment.Status.APPROVED,
        created_by=actor, approved_by=actor, approved_at=timezone.now(),
    )
