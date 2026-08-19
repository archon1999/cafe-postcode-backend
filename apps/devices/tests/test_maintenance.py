from datetime import timedelta

from django.test import TestCase, override_settings
from django.utils import timezone
from django_q.models import Schedule

from apps.devices.maintenance import (
    SECURITY_MAINTENANCE_SCHEDULE_FUNC,
    SECURITY_MAINTENANCE_SCHEDULE_NAME,
    cleanup_device_security_records,
    ensure_security_maintenance_schedule,
)
from apps.devices.models import DevicePairing, SecurityEvent


class DeviceSecurityMaintenanceTests(TestCase):
    def test_schedule_is_idempotent(self):
        self.assertTrue(ensure_security_maintenance_schedule())
        self.assertTrue(ensure_security_maintenance_schedule())
        schedule = Schedule.objects.get(name=SECURITY_MAINTENANCE_SCHEDULE_NAME)
        self.assertEqual(schedule.func, SECURITY_MAINTENANCE_SCHEDULE_FUNC)
        self.assertEqual(Schedule.objects.filter(name=SECURITY_MAINTENANCE_SCHEDULE_NAME).count(), 1)

    @override_settings(SECURITY_EVENT_RETENTION_DAYS=180, DEVICE_PAIRING_RETENTION_DAYS=30)
    def test_cleanup_expires_pending_and_removes_only_old_terminal_records(self):
        now = timezone.now()
        pending = DevicePairing.objects.create(
            device_type='POS_TERMINAL',
            requested_name='Pending',
            public_key_algorithm='P256_SHA256',
            public_key='public',
            public_key_fingerprint='a' * 64,
            poll_token_hash='b' * 64,
            claim_token_hash='c' * 64,
            display_code='123456',
            expires_at=now - timedelta(minutes=1),
        )
        old_pairing = DevicePairing.objects.create(
            device_type='POS_TERMINAL',
            requested_name='Old',
            public_key_algorithm='P256_SHA256',
            public_key='public',
            public_key_fingerprint='d' * 64,
            poll_token_hash='e' * 64,
            claim_token_hash='f' * 64,
            display_code='654321',
            status=DevicePairing.Status.REJECTED,
            expires_at=now,
        )
        DevicePairing.objects.filter(pk=old_pairing.pk).update(created_at=now - timedelta(days=31))
        old_event = SecurityEvent.objects.create(event_type='OLD', severity=SecurityEvent.Severity.INFO)
        SecurityEvent.objects.filter(pk=old_event.pk).update(created_at=now - timedelta(days=181))
        current_event = SecurityEvent.objects.create(event_type='CURRENT', severity=SecurityEvent.Severity.HIGH)

        result = cleanup_device_security_records()

        pending.refresh_from_db()
        self.assertEqual(pending.status, DevicePairing.Status.EXPIRED)
        self.assertFalse(DevicePairing.objects.filter(pk=old_pairing.pk).exists())
        self.assertFalse(SecurityEvent.objects.filter(pk=old_event.pk).exists())
        self.assertTrue(SecurityEvent.objects.filter(pk=current_event.pk).exists())
        self.assertEqual(result['expiredPairings'], 1)
