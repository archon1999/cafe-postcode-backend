from datetime import date, datetime, timedelta
from decimal import Decimal
from unittest.mock import PropertyMock, patch

from django.test import TestCase
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient

from apps.billing.models import Payment, PaymentRefund
from apps.catalog.models import CatalogItem
from apps.restaurants.models import Restaurant
from apps.sales.models import Order, OrderItem
from apps.users.models import AuthSession, User
from apps.workforce.models import GeofenceConfig, Timesheet

from apps.payroll.models import PayrollAdjustment, PayrollPayout, PayrollRun
from apps.payroll.api import period_data
from apps.payroll.services import (
    approve_pos_kpi, build_run, create_adjustment, create_kpi_rule,
    create_period, create_rate, decide_adjustment, kpi_preview, lock_runs,
    record_payout, void_payout,
)


class PayrollServiceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.restaurant = Restaurant.objects.create(name='Payroll Test Restaurant')
        cls.other_restaurant = Restaurant.objects.create(name='Other Payroll Restaurant')
        cls.manager = User.objects.create_user(
            username='payroll_manager', password='Password123!', full_name='Manager',
            restaurant=cls.restaurant,
        )
        cls.employee = User.objects.create_user(
            username='payroll_employee', password='Password123!', full_name='Employee',
            restaurant=cls.restaurant,
        )
        cls.other_employee = User.objects.create_user(
            username='other_payroll_employee', password='Password123!', full_name='Other',
            restaurant=cls.other_restaurant,
        )

    def period(self, start=date(2026, 9, 1), end=date(2026, 9, 30)):
        return create_period(
            restaurant=self.restaurant, label='September 2026',
            start_date=start, end_date=end,
        )

    def rate(self, *, rate_type='hourly', amount='10000', effective_from=date(2026, 9, 1)):
        return create_rate(
            restaurant=self.restaurant, employee_id=self.employee.pk,
            rate_type=rate_type, amount=amount, effective_from=effective_from,
            actor=self.manager,
        )

    def test_approved_timesheet_adjustments_locked_versions_and_manual_payout(self):
        period = self.period()
        self.rate()
        Timesheet.objects.create(
            restaurant=self.restaurant, employee=self.employee,
            work_date=date(2026, 9, 2), status=Timesheet.Status.APPROVED,
            approved_minutes=510, approved_shift_count=1,
        )
        unresolved = Timesheet.objects.create(
            restaurant=self.restaurant, employee=self.employee,
            work_date=date(2026, 9, 3), status=Timesheet.Status.DRAFT,
            approved_minutes=600, approved_shift_count=1,
        )
        bonus = create_adjustment(
            restaurant=self.restaurant, period_id=period.pk,
            employee_id=self.employee.pk, kind='bonus', amount='12000',
            reason='Guest feedback', actor=self.manager,
        )
        penalty = create_adjustment(
            restaurant=self.restaurant, period_id=period.pk,
            employee_id=self.employee.pk, kind='penalty', amount='2000',
            reason='Reviewed damage case', actor=self.manager,
        )
        decide_adjustment(restaurant=self.restaurant, adjustment_id=bonus.pk,
                          actor=self.manager, approve=True)
        decide_adjustment(restaurant=self.restaurant, adjustment_id=penalty.pk,
                          actor=self.manager, approve=True)
        run = build_run(restaurant=self.restaurant, period_id=period.pk,
                        employee_id=self.employee.pk, actor=self.manager)
        self.assertEqual(run.total, Decimal('95000.00'))
        self.assertEqual(build_run(restaurant=self.restaurant, period_id=period.pk,
                                   employee_id=self.employee.pk, actor=self.manager).pk, run.pk)
        with self.assertRaises(ValidationError):
            lock_runs(restaurant=self.restaurant, period_id=period.pk, actor=self.manager)
        unresolved.status = Timesheet.Status.APPROVED
        unresolved.approved_minutes = 0
        unresolved.approved_shift_count = 0
        unresolved.save(update_fields=['status', 'approved_minutes', 'approved_shift_count'])
        lock_runs(restaurant=self.restaurant, period_id=period.pk, actor=self.manager)
        run.refresh_from_db()
        self.assertEqual(run.status, PayrollRun.Status.LOCKED)
        payout = record_payout(
            restaurant=self.restaurant, period_id=period.pk,
            employee_id=self.employee.pk, amount='40000', method='cash',
            paid_at=timezone.now(), note='First installment', actor=self.manager,
        )
        with self.assertRaises(ValidationError):
            record_payout(
                restaurant=self.restaurant, period_id=period.pk,
                employee_id=self.employee.pk, amount='55000.01', method='cash',
                paid_at=timezone.now(), note='', actor=self.manager,
            )
        new_bonus = create_adjustment(
            restaurant=self.restaurant, period_id=period.pk,
            employee_id=self.employee.pk, kind='bonus', amount='5000',
            reason='Late award', actor=self.manager,
        )
        decide_adjustment(restaurant=self.restaurant, adjustment_id=new_bonus.pk,
                          actor=self.manager, approve=True)
        newer = build_run(restaurant=self.restaurant, period_id=period.pk,
                          employee_id=self.employee.pk, actor=self.manager)
        self.assertEqual(newer.version, 2)
        self.assertEqual(newer.total, Decimal('100000.00'))
        self.assertEqual(PayrollRun.objects.get(pk=run.pk).total, Decimal('95000.00'))
        with self.assertRaises(ValidationError):
            record_payout(
                restaurant=self.restaurant, period_id=period.pk,
                employee_id=self.employee.pk, amount='1000', method='cash',
                paid_at=timezone.now(), note='', actor=self.manager,
            )
        lock_runs(restaurant=self.restaurant, period_id=period.pk, actor=self.manager)
        void_payout(restaurant=self.restaurant, payout_id=payout.pk,
                    reason='Duplicate manual entry', actor=self.manager)
        payout.refresh_from_db()
        self.assertIsNotNone(payout.voided_at)
        self.assertEqual(PayrollPayout.objects.filter(period=period, voided_at__isnull=True).count(), 0)

    def test_monthly_rate_changes_are_weighted_by_effective_days(self):
        period = self.period()
        self.rate(rate_type='monthly', amount='3000000')
        self.rate(rate_type='monthly', amount='6000000', effective_from=date(2026, 9, 16))
        run = build_run(restaurant=self.restaurant, period_id=period.pk,
                        employee_id=self.employee.pk, actor=self.manager)
        self.assertEqual(run.total, Decimal('4500000.00'))

    def test_monthly_base_is_full_for_partial_period_without_attendance(self):
        period = self.period(start=date(2026, 9, 16), end=date(2026, 9, 30))
        self.rate(rate_type='monthly', amount='3000000')
        run = build_run(restaurant=self.restaurant, period_id=period.pk,
                        employee_id=self.employee.pk, actor=self.manager)
        self.assertEqual(run.total, Decimal('3000000.00'))
        self.assertEqual(run.lines[0]['quantity'], '1.000')
        self.assertEqual(run.lines[0]['unit'], 'period')

    def test_locked_snapshot_stays_visible_and_relock_rejects_overpaid_revision(self):
        period = self.period()
        self.rate(rate_type='hourly', amount='50000')
        Timesheet.objects.create(
            restaurant=self.restaurant, employee=self.employee,
            work_date=date(2026, 9, 2), status=Timesheet.Status.APPROVED,
            approved_minutes=120, approved_shift_count=1,
        )
        original = build_run(restaurant=self.restaurant, period_id=period.pk,
                             employee_id=self.employee.pk, actor=self.manager)
        lock_runs(restaurant=self.restaurant, period_id=period.pk, actor=self.manager)
        payout = record_payout(
            restaurant=self.restaurant, period_id=period.pk,
            employee_id=self.employee.pk, amount='80000', method='cash',
            paid_at=timezone.now(), note='', actor=self.manager,
        )
        deduction = create_adjustment(
            restaurant=self.restaurant, period_id=period.pk,
            employee_id=self.employee.pk, kind='deduction', amount='30000',
            reason='Approved unpaid leave', actor=self.manager,
        )
        decide_adjustment(restaurant=self.restaurant, adjustment_id=deduction.pk,
                          actor=self.manager, approve=True)
        revision = build_run(restaurant=self.restaurant, period_id=period.pk,
                             employee_id=self.employee.pk, actor=self.manager)
        self.assertEqual(revision.total, Decimal('70000.00'))
        self.assertEqual(period_data(period, employee=self.employee, locked_only=True)['total'], '100000.00')
        with self.assertRaises(ValidationError):
            lock_runs(restaurant=self.restaurant, period_id=period.pk, actor=self.manager)
        self.assertEqual(PayrollRun.objects.get(pk=original.pk).status, PayrollRun.Status.LOCKED)
        self.assertEqual(PayrollRun.objects.get(pk=revision.pk).status, PayrollRun.Status.DRAFT)
        void_payout(restaurant=self.restaurant, payout_id=payout.pk,
                    reason='Incorrect payment record', actor=self.manager)
        lock_runs(restaurant=self.restaurant, period_id=period.pk, actor=self.manager)
        self.assertEqual(PayrollRun.objects.get(pk=revision.pk).status, PayrollRun.Status.LOCKED)

    def test_pos_kpi_allocates_net_paid_sales_by_item_creator(self):
        period = self.period()
        self.rate()
        create_kpi_rule(restaurant=self.restaurant, role_id=None, percent='10',
                        effective_from=date(2026, 9, 1), actor=self.manager)
        order = Order.objects.create(
            restaurant=self.restaurant, status=Order.Status.CLOSED,
            order_number=1, closed_at=timezone.make_aware(datetime(2026, 9, 8, 12)),
            subtotal=100000, total=80000,
        )
        item = CatalogItem.objects.create(restaurant=self.restaurant, name='Coffee', price=10000)
        OrderItem.objects.create(order=order, catalog_item=item, created_by=self.employee,
                                 quantity=1, unit_price=60000)
        OrderItem.objects.create(order=order, catalog_item=item, created_by=None,
                                 quantity=1, unit_price=40000)
        OrderItem.objects.create(order=order, catalog_item=item, created_by=self.employee,
                                 quantity=1, unit_price=99999, status=OrderItem.Status.CANCELLED)
        payment = Payment.objects.create(order=order, status=Payment.Status.SUCCEEDED,
                                         amount=80000, paid_at=timezone.now())
        PaymentRefund.objects.create(payment=payment, status=PaymentRefund.Status.SUCCEEDED,
                                     amount=20000, refunded_at=timezone.now())
        preview = kpi_preview(restaurant=self.restaurant, period_id=period.pk,
                              employee_id=self.employee.pk)
        self.assertEqual(preview['netSales'], '36000.00')
        self.assertEqual(preview['amount'], '3600.00')
        approved = approve_pos_kpi(restaurant=self.restaurant, period_id=period.pk,
                                   employee_id=self.employee.pk, actor=self.manager)
        self.assertEqual(approved.status, PayrollAdjustment.Status.APPROVED)
        with self.assertRaises(ValidationError):
            approve_pos_kpi(restaurant=self.restaurant, period_id=period.pk,
                            employee_id=self.employee.pk, actor=self.manager)

    def test_pos_kpi_excludes_service_fee_and_allocates_override_discount(self):
        period = self.period()
        create_kpi_rule(restaurant=self.restaurant, role_id=None, percent='10',
                        effective_from=date(2026, 9, 1), actor=self.manager)
        order = Order.objects.create(
            restaurant=self.restaurant, status=Order.Status.CLOSED,
            order_number=2, closed_at=timezone.make_aware(datetime(2026, 9, 9, 12)),
            subtotal=100000, calculated_total=110000, total=100000,
            total_override=100000,
        )
        item = CatalogItem.objects.create(restaurant=self.restaurant, name='Lunch', price=100000)
        OrderItem.objects.create(order=order, catalog_item=item, created_by=self.employee,
                                 quantity=1, unit_price=100000)
        Payment.objects.create(order=order, status=Payment.Status.SUCCEEDED,
                               amount=100000, paid_at=timezone.now())
        preview = kpi_preview(restaurant=self.restaurant, period_id=period.pk,
                              employee_id=self.employee.pk)
        self.assertEqual(preview['netSales'], '90909.09')
        self.assertEqual(preview['amount'], '9090.91')

    def test_refund_after_kpi_approval_requires_new_approval_before_first_lock(self):
        period = self.period()
        self.rate(rate_type='monthly', amount='3000000')
        create_kpi_rule(restaurant=self.restaurant, role_id=None, percent='10',
                        effective_from=date(2026, 9, 1), actor=self.manager)
        order = Order.objects.create(
            restaurant=self.restaurant, status=Order.Status.CLOSED,
            order_number=3, closed_at=timezone.make_aware(datetime(2026, 9, 10, 12)),
            subtotal=100000, total=100000,
        )
        item = CatalogItem.objects.create(restaurant=self.restaurant, name='Dinner', price=100000)
        OrderItem.objects.create(order=order, catalog_item=item, created_by=self.employee,
                                 quantity=1, unit_price=100000)
        payment = Payment.objects.create(order=order, status=Payment.Status.SUCCEEDED,
                                         amount=100000, paid_at=timezone.now())
        original = approve_pos_kpi(restaurant=self.restaurant, period_id=period.pk,
                                   employee_id=self.employee.pk, actor=self.manager)
        self.assertEqual(original.amount, Decimal('10000.00'))
        PaymentRefund.objects.create(payment=payment, status=PaymentRefund.Status.SUCCEEDED,
                                     amount=20000, refunded_at=timezone.now())
        with self.assertRaises(ValidationError):
            lock_runs(restaurant=self.restaurant, period_id=period.pk, actor=self.manager)
        replacement = approve_pos_kpi(restaurant=self.restaurant, period_id=period.pk,
                                      employee_id=self.employee.pk, actor=self.manager)
        original.refresh_from_db()
        self.assertEqual(original.status, PayrollAdjustment.Status.SUPERSEDED)
        self.assertEqual(replacement.amount, Decimal('8000.00'))
        locked = lock_runs(restaurant=self.restaurant, period_id=period.pk, actor=self.manager)
        self.assertEqual(len(locked), 1)
        self.assertEqual(locked[0].total, Decimal('3008000.00'))
        with self.assertRaises(ValidationError):
            approve_pos_kpi(restaurant=self.restaurant, period_id=period.pk,
                            employee_id=self.employee.pk, actor=self.manager)
        self.assertEqual(PayrollAdjustment.objects.filter(
            period=period, origin=PayrollAdjustment.Origin.POS,
            status=PayrollAdjustment.Status.APPROVED,
        ).count(), 1)

    def test_full_refund_can_remove_approved_kpi_before_first_lock(self):
        period = self.period()
        self.rate(rate_type='monthly', amount='3000000')
        create_kpi_rule(restaurant=self.restaurant, role_id=None, percent='10',
                        effective_from=date(2026, 9, 1), actor=self.manager)
        order = Order.objects.create(
            restaurant=self.restaurant, status=Order.Status.CLOSED,
            order_number=4, closed_at=timezone.make_aware(datetime(2026, 9, 11, 12)),
            subtotal=100000, total=100000,
        )
        item = CatalogItem.objects.create(restaurant=self.restaurant, name='Dinner', price=100000)
        OrderItem.objects.create(order=order, catalog_item=item, created_by=self.employee,
                                 quantity=1, unit_price=100000)
        payment = Payment.objects.create(order=order, status=Payment.Status.SUCCEEDED,
                                         amount=100000, paid_at=timezone.now())
        original = approve_pos_kpi(restaurant=self.restaurant, period_id=period.pk,
                                   employee_id=self.employee.pk, actor=self.manager)
        PaymentRefund.objects.create(payment=payment, status=PaymentRefund.Status.SUCCEEDED,
                                     amount=100000, refunded_at=timezone.now())
        with self.assertRaises(ValidationError):
            lock_runs(restaurant=self.restaurant, period_id=period.pk, actor=self.manager)
        removed = approve_pos_kpi(restaurant=self.restaurant, period_id=period.pk,
                                  employee_id=self.employee.pk, actor=self.manager)
        self.assertEqual(removed.pk, original.pk)
        self.assertEqual(removed.status, PayrollAdjustment.Status.SUPERSEDED)
        self.assertEqual(lock_runs(restaurant=self.restaurant, period_id=period.pk,
                                   actor=self.manager)[0].total, Decimal('3000000.00'))

    def test_negative_net_payroll_cannot_be_locked(self):
        period = self.period()
        self.rate(rate_type='monthly', amount='100000')
        penalty = create_adjustment(
            restaurant=self.restaurant, period_id=period.pk,
            employee_id=self.employee.pk, kind='penalty', amount='120000',
            reason='Reviewed deduction', actor=self.manager,
        )
        decide_adjustment(restaurant=self.restaurant, adjustment_id=penalty.pk,
                          actor=self.manager, approve=True)
        with self.assertRaises(ValidationError):
            lock_runs(restaurant=self.restaurant, period_id=period.pk, actor=self.manager)

    def test_tenant_ids_are_rejected(self):
        period = self.period()
        with self.assertRaises(ValidationError):
            create_rate(restaurant=self.restaurant, employee_id=self.other_employee.pk,
                        rate_type='hourly', amount='1000',
                        effective_from=date(2026, 9, 1), actor=self.manager)
        with self.assertRaises(ValidationError):
            create_adjustment(restaurant=self.other_restaurant, period_id=period.pk,
                              employee_id=self.other_employee.pk, kind='bonus',
                              amount='1000', reason='Wrong tenant', actor=self.manager)

    def test_advance_requires_manual_disbursement_audit(self):
        period = self.period()
        with self.assertRaises(ValidationError):
            create_adjustment(restaurant=self.restaurant, period_id=period.pk,
                              employee_id=self.employee.pk, kind='advance',
                              amount='50000', reason='Advance', actor=self.manager)
        row = create_adjustment(
            restaurant=self.restaurant, period_id=period.pk,
            employee_id=self.employee.pk, kind='advance', amount='50000',
            reason='Cash advance', payment_method='cash',
            disbursed_at=timezone.now(), actor=self.manager,
        )
        self.assertEqual(row.evidence['paymentMethod'], 'cash')
        self.assertIn('disbursedAt', row.evidence)

    def test_api_requires_staff_surface_rollout_and_payroll_permission(self):
        client = APIClient()
        session = AuthSession.objects.create(
            user=self.manager, restaurant=self.restaurant,
            surface=AuthSession.Surface.ADMIN, token_key_hash='a' * 64,
            expires_at=timezone.now() + timedelta(hours=1),
        )
        client.force_authenticate(user=self.manager, token=session)
        with patch.object(User, 'restaurant_access_active', new_callable=PropertyMock, return_value=True):
            self.assertEqual(client.get('/api/v1/staff/payroll/me/periods/').status_code, 403)
            session.surface = AuthSession.Surface.STAFF
            self.assertEqual(client.get('/api/v1/staff/payroll/me/periods/').status_code, 403)
            GeofenceConfig.objects.create(restaurant=self.restaurant, workforce_enabled=True)
            self.assertEqual(client.get('/api/v1/staff/payroll/me/periods/').status_code, 200)
            self.assertEqual(client.get('/api/v1/staff/payroll/manager/periods/').status_code, 403)
            with patch.object(User, 'permission_codes', new_callable=PropertyMock,
                              return_value=['staff.payroll.view']):
                self.assertEqual(client.get('/api/v1/staff/payroll/manager/periods/').status_code, 200)
                self.assertEqual(client.post('/api/v1/staff/payroll/manager/periods/', {
                    'label': 'September', 'startDate': '2026-09-01', 'endDate': '2026-09-30',
                }, format='json').status_code, 403)

    def test_employee_cannot_read_another_restaurants_locked_payroll(self):
        period = self.period()
        self.rate()
        build_run(restaurant=self.restaurant, period_id=period.pk,
                  employee_id=self.employee.pk, actor=self.manager)
        lock_runs(restaurant=self.restaurant, period_id=period.pk, actor=self.manager)
        GeofenceConfig.objects.create(restaurant=self.other_restaurant, workforce_enabled=True)
        session = AuthSession.objects.create(
            user=self.other_employee, restaurant=self.other_restaurant,
            surface=AuthSession.Surface.STAFF, token_key_hash='b' * 64,
            expires_at=timezone.now() + timedelta(hours=1),
        )
        client = APIClient()
        client.force_authenticate(user=self.other_employee, token=session)
        with patch.object(User, 'restaurant_access_active', new_callable=PropertyMock, return_value=True):
            response = client.get(f'/api/v1/staff/payroll/me/periods/{period.pk}/')
        self.assertEqual(response.status_code, 404)

    def test_employee_period_list_preserves_period_id(self):
        period = self.period()
        self.rate()
        build_run(restaurant=self.restaurant, period_id=period.pk,
                  employee_id=self.employee.pk, actor=self.manager)
        lock_runs(restaurant=self.restaurant, period_id=period.pk, actor=self.manager)
        GeofenceConfig.objects.create(restaurant=self.restaurant, workforce_enabled=True)
        session = AuthSession.objects.create(
            user=self.employee, restaurant=self.restaurant,
            surface=AuthSession.Surface.STAFF, token_key_hash='c' * 64,
            expires_at=timezone.now() + timedelta(hours=1),
        )
        client = APIClient()
        client.force_authenticate(user=self.employee, token=session)
        with patch.object(User, 'restaurant_access_active', new_callable=PropertyMock, return_value=True):
            response = client.get('/api/v1/staff/payroll/me/periods/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['results'][0]['id'], str(period.pk))
        self.assertEqual(response.data['results'][0]['run_id'], str(period.runs.first().pk))

    def test_manager_api_builds_and_records_manual_payment(self):
        GeofenceConfig.objects.create(restaurant=self.restaurant, workforce_enabled=True)
        session = AuthSession.objects.create(
            user=self.manager, restaurant=self.restaurant,
            surface=AuthSession.Surface.STAFF, token_key_hash='d' * 64,
            expires_at=timezone.now() + timedelta(hours=1),
        )
        client = APIClient()
        client.force_authenticate(user=self.manager, token=session)
        codes = ['staff.payroll.view', 'staff.payroll.manage', 'staff.payroll.payout']
        with patch.object(User, 'restaurant_access_active', new_callable=PropertyMock, return_value=True), \
             patch.object(User, 'permission_codes', new_callable=PropertyMock, return_value=codes):
            response = client.post('/api/v1/staff/payroll/manager/periods/', {
                'label': 'September', 'startDate': '2026-09-01', 'endDate': '2026-09-30',
            }, format='json')
            self.assertEqual(response.status_code, 201, response.data)
            period_id = response.data['id']
            response = client.post('/api/v1/staff/payroll/manager/rates/', {
                'employeeId': str(self.employee.pk), 'rateType': 'hourly',
                'amount': '10000.00', 'effectiveFrom': '2026-09-01',
            }, format='json')
            self.assertEqual(response.status_code, 201, response.data)
            Timesheet.objects.create(
                restaurant=self.restaurant, employee=self.employee,
                work_date=date(2026, 9, 2), status=Timesheet.Status.APPROVED,
                approved_minutes=120, approved_shift_count=1,
            )
            base = f'/api/v1/staff/payroll/manager/periods/{period_id}'
            self.assertEqual(client.post(f'{base}/runs/build/', {}, format='json').status_code, 200)
            self.assertEqual(client.post(f'{base}/runs/lock/', {}, format='json').status_code, 200)
            response = client.post(f'{base}/payouts/', {
                'employeeId': str(self.employee.pk), 'amount': '10000.00',
                'method': 'external_transfer', 'paidAt': timezone.now().isoformat(),
                'note': 'Recorded after manual transfer',
            }, format='json')
            self.assertEqual(response.status_code, 201, response.data)
            self.assertEqual(response.data['amount'], '10000.00')
            detail = client.get(f'{base}/')
            self.assertEqual(detail.status_code, 200)
            self.assertEqual(detail.data['runs'][0]['remaining'], '10000.00')
