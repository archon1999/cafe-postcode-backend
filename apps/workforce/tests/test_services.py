from datetime import datetime, time, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.restaurants.models import Restaurant
from apps.users.models import User
from apps.workforce.models import AttendancePunch, CorrectionRequest, GeofenceConfig, Shift, Timesheet, WeeklyScheduleTemplate
from apps.workforce.services import (
    approve_timesheet, create_device_punch, create_pwa_punch,
    generate_draft_shifts, resolve_correction,
)


class WorkforceServiceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.restaurant = Restaurant.objects.create(name='Workforce pilot')
        cls.employee = User.objects.create_user(
            username='workforce-employee', password='temporary-password',
            full_name='Workforce Employee', restaurant=cls.restaurant,
        )
        cls.manager = User.objects.create_user(
            username='workforce-manager', password='temporary-password',
            full_name='Workforce Manager', restaurant=cls.restaurant,
        )
        cls.geofence = GeofenceConfig.objects.create(
            restaurant=cls.restaurant, workforce_enabled=True,
            enabled=True, latitude=Decimal('41.311081'), longitude=Decimal('69.240562'), radius_meters=150,
        )

    @staticmethod
    def at(day, clock):
        return timezone.make_aware(datetime.combine(day, clock), timezone.get_current_timezone())

    def test_geofence_outside_is_saved_and_retry_does_not_duplicate(self):
        first, duplicate = create_pwa_punch(
            restaurant=self.restaurant, employee=self.employee,
            event_type='in', source_event_id='uuid-outside-0001',
            latitude=Decimal('41.320000'), longitude=Decimal('69.240562'), accuracy_meters=20,
        )
        self.assertFalse(duplicate)
        self.assertEqual(first.geo_status, AttendancePunch.GeoStatus.OUTSIDE)
        self.assertTrue(first.requires_review)
        self.assertIn('outside_geofence', first.review_reasons)
        retry, duplicate = create_pwa_punch(
            restaurant=self.restaurant, employee=self.employee,
            event_type='in', source_event_id='uuid-outside-0001',
        )
        self.assertTrue(duplicate)
        self.assertEqual(retry.id, first.id)
        self.assertEqual(AttendancePunch.objects.count(), 1)
        with self.assertRaises(ValidationError):
            create_pwa_punch(
                restaurant=self.restaurant, employee=self.employee,
                event_type='out', source_event_id='uuid-outside-0001',
            )

    def test_offline_without_gps_is_provisional_and_requires_review(self):
        recorded = timezone.now() - timedelta(minutes=7)
        punch, _ = create_pwa_punch(
            restaurant=self.restaurant, employee=self.employee,
            event_type='in', source_event_id='offline-event-001',
            client_recorded_at=recorded, offline=True,
        )
        self.assertEqual(punch.occurred_at, recorded)
        self.assertTrue(punch.provisional)
        self.assertEqual(punch.geo_status, AttendancePunch.GeoStatus.UNAVAILABLE)
        self.assertCountEqual(punch.review_reasons, ['location_unavailable', 'offline_submission'])

    def test_overnight_shift_preserves_work_date_and_approved_hours(self):
        now = timezone.localtime(timezone.now())
        start_date = now.date() - timedelta(days=2)
        start = self.at(start_date, time(22, 0))
        end = self.at(start_date + timedelta(days=1), time(6, 0))
        Shift.objects.create(
            restaurant=self.restaurant, employee=self.employee,
            starts_at=start, ends_at=end, status=Shift.Status.PUBLISHED,
        )
        # Device punches preserve the device event time and the shift's work date.
        with patch('apps.workforce.services.timezone.now', return_value=end + timedelta(minutes=10)):
            first, _ = create_device_punch(
                restaurant=self.restaurant, employee=self.employee,
                event_type='in', source_event_id='terminal1:event1', device_recorded_at=start,
            )
            second, _ = create_device_punch(
                restaurant=self.restaurant, employee=self.employee,
                event_type='out', source_event_id='terminal1:event2', device_recorded_at=end,
            )
        self.assertEqual(first.work_date, start_date)
        self.assertEqual(second.work_date, start_date)
        sheet = Timesheet.objects.get(restaurant=self.restaurant, employee=self.employee, work_date=start_date)
        self.assertEqual(sheet.approved_minutes, 480)
        self.assertEqual(sheet.approved_shift_count, 1)
        self.assertEqual(sheet.period_start, start)
        self.assertEqual(sheet.period_end, end)
        self.assertTrue(sheet.requires_review)  # Delayed device import is visible to the manager.
        approved = approve_timesheet(timesheet=sheet, manager=self.manager, note='Verified terminal import')
        self.assertEqual(approved.status, Timesheet.Status.APPROVED)

    def test_correction_sets_draft_and_approval_locks_it(self):
        day = timezone.localdate()
        start = self.at(day, time(9, 0))
        end = self.at(day, time(17, 0))
        correction = CorrectionRequest.objects.create(
            restaurant=self.restaurant, employee=self.employee, work_date=day,
            proposed_start_at=start, proposed_end_at=end, proposed_break_minutes=30,
            reason='Missed punch at opening',
        )
        resolved = resolve_correction(
            correction=correction, manager=self.manager,
            decision=CorrectionRequest.Status.APPROVED, note='Checked camera log',
        )
        self.assertEqual(resolved.status, CorrectionRequest.Status.APPROVED)
        sheet = Timesheet.objects.get(restaurant=self.restaurant, employee=self.employee, work_date=day)
        self.assertTrue(sheet.manual_override)
        self.assertEqual(sheet.approved_minutes, 450)
        approve_timesheet(timesheet=sheet, manager=self.manager, note='Approved exception')
        next_correction = CorrectionRequest.objects.create(
            restaurant=self.restaurant, employee=self.employee, work_date=day,
            proposed_start_at=start, proposed_end_at=end + timedelta(hours=1),
            reason='Later change',
        )
        with self.assertRaises(ValidationError):
            resolve_correction(
                correction=next_correction, manager=self.manager,
                decision=CorrectionRequest.Status.APPROVED,
            )

    def test_weekly_template_generates_overnight_drafts_once(self):
        day = timezone.localdate()
        WeeklyScheduleTemplate.objects.create(
            restaurant=self.restaurant, employee=self.employee, weekday=day.weekday(),
            start_time=time(22, 0), end_time=time(6, 0), effective_from=day,
        )
        self.assertEqual(generate_draft_shifts(restaurant=self.restaurant, start_date=day, end_date=day), 1)
        self.assertEqual(generate_draft_shifts(restaurant=self.restaurant, start_date=day, end_date=day), 0)
        shift = Shift.objects.get()
        self.assertEqual(shift.ends_at - shift.starts_at, timedelta(hours=8))

    def test_scheduled_break_is_deducted_and_flagged_until_review(self):
        now = timezone.now()
        start = now - timedelta(hours=8)
        finish = now - timedelta(minutes=1)
        shift = Shift.objects.create(
            restaurant=self.restaurant, employee=self.employee,
            starts_at=start, ends_at=finish, status=Shift.Status.PUBLISHED,
            unpaid_break_minutes=30,
        )
        with patch('apps.workforce.services.timezone.now', return_value=now):
            create_device_punch(
                restaurant=self.restaurant, employee=self.employee,
                event_type='in', source_event_id='terminal2:start', device_recorded_at=start,
            )
            create_device_punch(
                restaurant=self.restaurant, employee=self.employee,
                event_type='out', source_event_id='terminal2:end', device_recorded_at=finish,
            )
        sheet = Timesheet.objects.get(restaurant=self.restaurant, employee=self.employee)
        self.assertEqual(sheet.shift, shift)
        self.assertEqual(sheet.break_minutes, 30)
        self.assertEqual(sheet.approved_minutes, 449)
        self.assertIn('scheduled_break_unconfirmed', sheet.review_reasons)

    def test_historical_device_delivery_does_not_look_like_clock_skew(self):
        now = timezone.now()
        event_time = now - timedelta(days=1)
        with patch('apps.workforce.services.timezone.now', return_value=now):
            punch, _ = create_device_punch(
                restaurant=self.restaurant, employee=self.employee,
                event_type='in', source_event_id='terminal3:old-event',
                device_recorded_at=event_time, device_clock_at_poll=now,
            )
        self.assertEqual(punch.clock_skew_seconds, 0)
        self.assertIn('delayed_import', punch.review_reasons)
        self.assertNotIn('device_clock_skew', punch.review_reasons)

    def test_mixed_pwa_and_terminal_duplicate_punches_preserve_first_interval(self):
        receipt_time = timezone.now()
        start = receipt_time - timedelta(hours=8)
        finish = receipt_time - timedelta(minutes=1)
        Shift.objects.create(
            restaurant=self.restaurant, employee=self.employee,
            starts_at=start, ends_at=finish, status=Shift.Status.PUBLISHED,
        )
        with patch('apps.workforce.services.timezone.now', return_value=start):
            create_pwa_punch(
                restaurant=self.restaurant, employee=self.employee,
                event_type='in', source_event_id='mixed-pwa-start',
                latitude=Decimal('41.311081'), longitude=Decimal('69.240562'), accuracy_meters=20,
            )
        with patch('apps.workforce.services.timezone.now', return_value=receipt_time):
            create_device_punch(
                restaurant=self.restaurant, employee=self.employee,
                event_type='in', source_event_id='mixed-terminal-start',
                device_recorded_at=start + timedelta(minutes=1), device_clock_at_poll=receipt_time,
            )
            create_device_punch(
                restaurant=self.restaurant, employee=self.employee,
                event_type='out', source_event_id='mixed-terminal-end',
                device_recorded_at=finish, device_clock_at_poll=receipt_time,
            )
            create_device_punch(
                restaurant=self.restaurant, employee=self.employee,
                event_type='out', source_event_id='mixed-terminal-duplicate-end',
                device_recorded_at=finish + timedelta(seconds=10), device_clock_at_poll=receipt_time,
            )
        sheet = Timesheet.objects.get(restaurant=self.restaurant, employee=self.employee)
        self.assertEqual(sheet.period_start, start)
        self.assertEqual(sheet.period_end, finish)
        self.assertEqual(sheet.approved_minutes, 479)
        self.assertEqual(sheet.approved_shift_count, 1)
        self.assertIn('duplicate_in', sheet.review_reasons)
        self.assertIn('duplicate_out', sheet.review_reasons)
