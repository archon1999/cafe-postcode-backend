from datetime import timedelta

from django.conf import settings
from django.db.utils import OperationalError, ProgrammingError
from django.utils import timezone

from apps.devices.models import DevicePairing, SecurityEvent


SECURITY_MAINTENANCE_SCHEDULE_NAME = 'devices.security-maintenance'
SECURITY_MAINTENANCE_SCHEDULE_FUNC = 'apps.devices.maintenance.cleanup_device_security_records'
SECURITY_MAINTENANCE_CRON = '25 2 * * *'


def cleanup_device_security_records() -> dict[str, int]:
    now = timezone.now()
    expired_pairings = DevicePairing.objects.filter(
        status=DevicePairing.Status.PENDING,
        expires_at__lte=now,
    ).update(status=DevicePairing.Status.EXPIRED)
    pairing_cutoff = now - timedelta(days=max(1, settings.DEVICE_PAIRING_RETENTION_DAYS))
    deleted_pairings, _ = DevicePairing.objects.exclude(status=DevicePairing.Status.PENDING).filter(
        created_at__lt=pairing_cutoff,
    ).delete()
    event_cutoff = now - timedelta(days=max(30, settings.SECURITY_EVENT_RETENTION_DAYS))
    deleted_events, _ = SecurityEvent.objects.filter(created_at__lt=event_cutoff).delete()
    return {
        'expiredPairings': expired_pairings,
        'deletedPairings': deleted_pairings,
        'deletedSecurityEvents': deleted_events,
    }


def ensure_security_maintenance_schedule() -> bool:
    from croniter import croniter
    from django_q.models import Schedule

    try:
        local_now = timezone.localtime()
        next_run = croniter(SECURITY_MAINTENANCE_CRON, local_now).get_next(type(local_now))
        Schedule.objects.update_or_create(
            name=SECURITY_MAINTENANCE_SCHEDULE_NAME,
            defaults={
                'func': SECURITY_MAINTENANCE_SCHEDULE_FUNC,
                'schedule_type': Schedule.CRON,
                'cron': SECURITY_MAINTENANCE_CRON,
                'repeats': -1,
                'next_run': next_run,
            },
        )
    except (ProgrammingError, OperationalError):
        return False
    return True
