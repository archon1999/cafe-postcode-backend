from decimal import Decimal

from django.shortcuts import get_object_or_404
from rest_framework import permissions, serializers
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.users.models import AuthSession
from apps.workforce.models import GeofenceConfig
from common.api.scopes import get_request_restaurant

from .models import CompensationRate, KpiRule, PayrollAdjustment, PayrollPayout, PayrollPeriod, PayrollRun
from .services import (
    approve_pos_kpi, build_all_runs, create_adjustment, create_kpi_rule,
    create_period, create_rate, decide_adjustment, kpi_preview, lock_runs,
    paid_amount, record_payout, void_payout,
)


class StaffSessionRequired(permissions.BasePermission):
    message = 'An active staff session is required.'

    def has_permission(self, request, view):
        session = request.auth
        restaurant = request.user.get_restaurant_scope() if getattr(request.user, 'is_authenticated', False) else None
        return bool(
            getattr(request.user, 'is_authenticated', False)
            and isinstance(session, AuthSession)
            and session.surface == 'staff'
            and restaurant is not None
            and session.restaurant_id == restaurant.pk
            and request.user.restaurant_access_active
            and GeofenceConfig.objects.filter(restaurant=restaurant, workforce_enabled=True).exists()
        )


class PayrollCodeRequired(permissions.BasePermission):
    message = 'Payroll permission is required.'

    def has_permission(self, request, view):
        code = getattr(view, 'required_code', None)
        return bool(code and code in request.user.permission_codes)


class StaffView(APIView):
    permission_classes = [StaffSessionRequired]

    def restaurant(self):
        return get_request_restaurant(self.request)


class ManagerView(StaffView):
    permission_classes = [StaffSessionRequired, PayrollCodeRequired]
    required_code = 'staff.payroll.view'


class ManagerWriteView(ManagerView):
    required_code = 'staff.payroll.manage'


class PayoutWriteView(ManagerView):
    required_code = 'staff.payroll.payout'


class PeriodInput(serializers.Serializer):
    label = serializers.CharField(max_length=120, allow_blank=True, required=False, default='')
    start_date = serializers.DateField()
    end_date = serializers.DateField()


class RateInput(serializers.Serializer):
    employee_id = serializers.UUIDField()
    rate_type = serializers.ChoiceField(choices=CompensationRate.Type.choices)
    amount = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal('0.01'))
    effective_from = serializers.DateField()


class KpiRuleInput(serializers.Serializer):
    role_id = serializers.UUIDField(required=False, allow_null=True, default=None)
    percent = serializers.DecimalField(max_digits=6, decimal_places=3, min_value=Decimal('0'), max_value=Decimal('100'))
    effective_from = serializers.DateField()


class AdjustmentInput(serializers.Serializer):
    employee_id = serializers.UUIDField()
    kind = serializers.ChoiceField(choices=PayrollAdjustment.Kind.choices)
    amount = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal('0.01'))
    reason = serializers.CharField(allow_blank=False)
    payment_method = serializers.ChoiceField(choices=PayrollPayout.Method.choices, required=False)
    disbursed_at = serializers.DateTimeField(required=False)


class EmployeeInput(serializers.Serializer):
    employee_id = serializers.UUIDField(required=False)


class PayoutInput(serializers.Serializer):
    employee_id = serializers.UUIDField()
    amount = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal('0.01'))
    method = serializers.ChoiceField(choices=PayrollPayout.Method.choices)
    paid_at = serializers.DateTimeField()
    note = serializers.CharField(required=False, allow_blank=True, default='')


class ReasonInput(serializers.Serializer):
    reason = serializers.CharField(allow_blank=False)


def _data(serializer_class, request):
    serializer = serializer_class(data=request.data)
    serializer.is_valid(raise_exception=True)
    return serializer.validated_data


def payout_data(payout):
    return {
        'id': str(payout.pk), 'employee_id': str(payout.employee_id),
        'amount': str(payout.amount), 'method': payout.method,
        'paid_at': payout.paid_at, 'note': payout.note,
        'recorded_by_id': str(payout.recorded_by_id),
        'voided_at': payout.voided_at, 'voided_by_id': str(payout.voided_by_id) if payout.voided_by_id else None,
        'void_reason': payout.void_reason,
    }


def run_data(run, *, include_lines=True):
    paid = paid_amount(period=run.period, employee=run.employee)
    result = {
        'id': str(run.pk), 'employee_id': str(run.employee_id),
        'employee_name': run.employee.full_name, 'version': run.version,
        'status': run.status, 'total': str(run.total),
        'paid': str(paid), 'remaining': str(run.total - paid),
        'locked_at': run.locked_at,
    }
    if include_lines:
        result['lines'] = run.lines
    return result


def period_data(period, *, employee=None, include_runs=False, locked_only=False):
    runs = PayrollRun.objects.filter(period=period).select_related('employee', 'period').order_by('employee_id', '-version')
    if employee:
        runs = runs.filter(employee=employee)
    if locked_only:
        runs = runs.filter(status=PayrollRun.Status.LOCKED)
    latest = {}
    for row in runs:
        latest.setdefault(row.employee_id, row)
    data = {
        'id': str(period.pk), 'label': period.label,
        'start_date': period.start_date, 'end_date': period.end_date,
        'status': period.status,
    }
    if employee:
        run = latest.get(employee.pk)
        if run:
            detail = run_data(run)
            data['run_id'] = detail.pop('id')
            data.update(detail)
        else:
            data.update({'total': '0.00', 'paid': '0.00', 'remaining': '0.00', 'lines': []})
        data['payouts'] = [payout_data(row) for row in PayrollPayout.objects.filter(period=period, employee=employee)]
    elif include_runs:
        data['runs'] = [run_data(row) for row in latest.values()]
        data['adjustments'] = [adjustment_data(row) for row in PayrollAdjustment.objects.filter(period=period).select_related('employee')]
        data['payouts'] = [payout_data(row) for row in PayrollPayout.objects.filter(period=period)]
    return data


def adjustment_data(row):
    return {
        'id': str(row.pk), 'employee_id': str(row.employee_id),
        'employee_name': row.employee.full_name,
        'kind': row.kind, 'origin': row.origin, 'amount': str(row.amount),
        'reason': row.reason, 'evidence': row.evidence, 'status': row.status,
        'created_at': row.created_at, 'approved_at': row.approved_at,
    }


class MyPeriodListView(StaffView):
    def get(self, request):
        restaurant = self.restaurant()
        periods = PayrollPeriod.objects.filter(restaurant=restaurant, runs__employee=request.user,
                                                runs__status=PayrollRun.Status.LOCKED).distinct()
        return Response({'results': [period_data(row, employee=request.user, locked_only=True) for row in periods]})


class MyPeriodDetailView(StaffView):
    def get(self, request, period_id):
        period = get_object_or_404(PayrollPeriod, pk=period_id, restaurant=self.restaurant())
        if not PayrollRun.objects.filter(period=period, employee=request.user,
                                         status=PayrollRun.Status.LOCKED).exists():
            from django.http import Http404
            raise Http404
        return Response(period_data(period, employee=request.user, locked_only=True))


class ManagerPeriodListView(ManagerView):
    def get(self, request):
        return Response({'results': [period_data(row) for row in PayrollPeriod.objects.filter(restaurant=self.restaurant())]})

    def post(self, request):
        if 'staff.payroll.manage' not in request.user.permission_codes:
            raise PermissionDenied('Payroll management permission is required.')
        data = _data(PeriodInput, request)
        period = create_period(restaurant=self.restaurant(), **data)
        return Response(period_data(period), status=201)


class ManagerPeriodDetailView(ManagerView):
    def get(self, request, period_id):
        period = get_object_or_404(PayrollPeriod, pk=period_id, restaurant=self.restaurant())
        return Response(period_data(period, include_runs=True))


class ManagerRateView(ManagerView):
    def get(self, request):
        queryset = CompensationRate.objects.filter(restaurant=self.restaurant()).select_related('employee')
        employee_id = request.query_params.get('employee_id')
        if employee_id:
            queryset = queryset.filter(employee_id=employee_id)
        return Response({'results': [{
            'id': str(row.pk), 'employee_id': str(row.employee_id),
            'employee_name': row.employee.full_name, 'rate_type': row.rate_type,
            'amount': str(row.amount), 'effective_from': row.effective_from,
        } for row in queryset]})

    def post(self, request):
        if 'staff.payroll.manage' not in request.user.permission_codes:
            raise PermissionDenied('Payroll management permission is required.')
        data = _data(RateInput, request)
        row = create_rate(restaurant=self.restaurant(), actor=request.user, **data)
        return Response({'id': str(row.pk), 'employee_id': str(row.employee_id),
                         'rate_type': row.rate_type, 'amount': str(row.amount),
                         'effective_from': row.effective_from}, status=201)


class ManagerKpiRuleView(ManagerView):
    def get(self, request):
        rows = KpiRule.objects.filter(restaurant=self.restaurant())
        return Response({'results': [{
            'id': str(row.pk), 'role_id': str(row.role_id) if row.role_id else None,
            'percent': str(row.percent), 'effective_from': row.effective_from,
        } for row in rows]})

    def post(self, request):
        if 'staff.payroll.manage' not in request.user.permission_codes:
            raise PermissionDenied('Payroll management permission is required.')
        row = create_kpi_rule(restaurant=self.restaurant(), actor=request.user,
                              **_data(KpiRuleInput, request))
        return Response({'id': str(row.pk), 'role_id': str(row.role_id) if row.role_id else None,
                         'percent': str(row.percent), 'effective_from': row.effective_from}, status=201)


class BuildRunsView(ManagerWriteView):
    def post(self, request, period_id):
        data = _data(EmployeeInput, request)
        rows = build_all_runs(restaurant=self.restaurant(), period_id=period_id,
                              actor=request.user, **data)
        return Response({'results': [run_data(row) for row in rows]})


class LockRunsView(ManagerWriteView):
    def post(self, request, period_id):
        rows = lock_runs(restaurant=self.restaurant(), period_id=period_id, actor=request.user)
        return Response({'results': [run_data(row) for row in rows]})


class AdjustmentCreateView(ManagerWriteView):
    def post(self, request, period_id):
        row = create_adjustment(restaurant=self.restaurant(), period_id=period_id,
                                actor=request.user, **_data(AdjustmentInput, request))
        return Response(adjustment_data(row), status=201)


class AdjustmentDecisionView(ManagerWriteView):
    approve = True

    def post(self, request, adjustment_id):
        row = decide_adjustment(restaurant=self.restaurant(), adjustment_id=adjustment_id,
                                actor=request.user, approve=self.approve)
        return Response(adjustment_data(row))


class AdjustmentRejectView(AdjustmentDecisionView):
    approve = False


class KpiPreviewView(ManagerView):
    def get(self, request, period_id):
        employee_id = request.query_params.get('employee_id')
        if not employee_id:
            raise serializers.ValidationError({'employeeId': 'Employee is required.'})
        return Response(kpi_preview(restaurant=self.restaurant(), period_id=period_id,
                                    employee_id=employee_id))


class KpiApproveView(ManagerWriteView):
    def post(self, request, period_id):
        data = _data(EmployeeInput, request)
        if not data.get('employee_id'):
            raise serializers.ValidationError({'employeeId': 'Employee is required.'})
        row = approve_pos_kpi(restaurant=self.restaurant(), period_id=period_id,
                              employee_id=data['employee_id'], actor=request.user)
        return Response(adjustment_data(row), status=201)


class PayoutCreateView(PayoutWriteView):
    def post(self, request, period_id):
        row = record_payout(restaurant=self.restaurant(), period_id=period_id,
                            actor=request.user, **_data(PayoutInput, request))
        return Response(payout_data(row), status=201)


class PayoutVoidView(PayoutWriteView):
    def post(self, request, payout_id):
        row = void_payout(restaurant=self.restaurant(), payout_id=payout_id,
                          actor=request.user, **_data(ReasonInput, request))
        return Response(payout_data(row))
