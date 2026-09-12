from datetime import timedelta
from django.test import SimpleTestCase
from django.utils import timezone
from .operational_health import normalize_health, assess_operational_health


class OperationalHealthTests(SimpleTestCase):
    def setUp(self):
        self.now = timezone.now()

    def report(self, checks):
        return normalize_health({'schemaVersion': 1, 'checkedAt': self.now.isoformat(), 'checks': checks}, self.now)

    def test_missing_and_stale_diagnostics_are_unknown(self):
        self.assertEqual(assess_operational_health({}, self.now)['status'], 'unknown')
        report = self.report([{'component': 'storage', 'state': 'ok'}])
        self.assertEqual(assess_operational_health(report, self.now + timedelta(hours=24, seconds=1))['status'], 'unknown')

    def test_diagnostics_remain_fresh_for_twenty_four_hours(self):
        report = self.report([{'component': 'storage', 'state': 'ok'}])
        for age in (timedelta(minutes=11), timedelta(hours=12), timedelta(hours=23), timedelta(hours=24)):
            with self.subTest(age=age):
                result = assess_operational_health(report, self.now + age)
                self.assertEqual(result['status'], 'healthy')
                self.assertEqual(result['freshnessMinutes'], 1440)

    def test_missing_diagnostics_publish_same_freshness_window(self):
        self.assertEqual(assess_operational_health({}, self.now)['freshnessMinutes'], 1440)

    def test_healthy_requires_storage_evidence(self):
        self.assertEqual(assess_operational_health(self.report([]), self.now)['status'], 'unknown')
        self.assertEqual(assess_operational_health(self.report([{'component': 'storage', 'state': 'ok'}]), self.now)['status'], 'healthy')

    def test_repeated_failures_and_recovery_are_component_scoped(self):
        checks = [{'component': 'storage', 'state': 'ok'}, {'component': 'printer', 'resource': 'cash', 'state': 'error', 'consecutiveFailures': 2}]
        self.assertEqual(assess_operational_health(self.report(checks), self.now)['status'], 'healthy')
        checks[1]['consecutiveFailures'] = 3
        self.assertEqual(assess_operational_health(self.report(checks), self.now)['status'], 'attention')
        checks[1]['state'] = 'ok'
        self.assertEqual(assess_operational_health(self.report(checks), self.now)['status'], 'healthy')
        checks[1].update(component='order_save', state='error')
        self.assertEqual(assess_operational_health(self.report(checks), self.now)['status'], 'critical')

    def test_confirmed_storage_failure_is_critical_immediately(self):
        self.assertEqual(assess_operational_health(self.report([{'component': 'storage', 'state': 'error', 'confirmed': True}]), self.now)['status'], 'critical')

    def test_unknown_runtime_is_not_healthy_and_invalid_reports_are_ignored(self):
        self.assertEqual(assess_operational_health(self.report([{'component': 'storage', 'state': 'ok'}, {'component': 'runtime', 'state': 'unknown'}]), self.now)['status'], 'unknown')
        self.assertIsNone(normalize_health({'schemaVersion': 1, 'checkedAt': 'invalid', 'checks': []}, self.now))
