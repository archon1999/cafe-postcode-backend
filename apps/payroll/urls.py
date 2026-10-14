from django.urls import path

from . import api


urlpatterns = [
    path('me/periods/', api.MyPeriodListView.as_view(), name='staff-payroll-my-periods'),
    path('me/periods/<uuid:period_id>/', api.MyPeriodDetailView.as_view(), name='staff-payroll-my-period'),
    path('manager/periods/', api.ManagerPeriodListView.as_view(), name='staff-payroll-periods'),
    path('manager/periods/<uuid:period_id>/', api.ManagerPeriodDetailView.as_view(), name='staff-payroll-period'),
    path('manager/periods/<uuid:period_id>/runs/build/', api.BuildRunsView.as_view(), name='staff-payroll-build'),
    path('manager/periods/<uuid:period_id>/runs/lock/', api.LockRunsView.as_view(), name='staff-payroll-lock'),
    path('manager/periods/<uuid:period_id>/adjustments/', api.AdjustmentCreateView.as_view(), name='staff-payroll-adjustments'),
    path('manager/adjustments/<uuid:adjustment_id>/approve/', api.AdjustmentDecisionView.as_view(), name='staff-payroll-adjustment-approve'),
    path('manager/adjustments/<uuid:adjustment_id>/reject/', api.AdjustmentRejectView.as_view(), name='staff-payroll-adjustment-reject'),
    path('manager/periods/<uuid:period_id>/kpi-preview/', api.KpiPreviewView.as_view(), name='staff-payroll-kpi-preview'),
    path('manager/periods/<uuid:period_id>/kpi-approve/', api.KpiApproveView.as_view(), name='staff-payroll-kpi-approve'),
    path('manager/periods/<uuid:period_id>/payouts/', api.PayoutCreateView.as_view(), name='staff-payroll-payouts'),
    path('manager/payouts/<uuid:payout_id>/void/', api.PayoutVoidView.as_view(), name='staff-payroll-payout-void'),
    path('manager/rates/', api.ManagerRateView.as_view(), name='staff-payroll-rates'),
    path('manager/kpi-rules/', api.ManagerKpiRuleView.as_view(), name='staff-payroll-kpi-rules'),
]
