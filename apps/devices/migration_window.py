from datetime import datetime, timezone as datetime_timezone

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.utils import timezone


def _timestamp(setting_name: str):
    value = str(getattr(settings, setting_name, '') or '').strip()
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as error:
        raise ImproperlyConfigured(f'{setting_name} is invalid.') from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ImproperlyConfigured(f'{setting_name} must include a timezone.')
    return parsed.astimezone(datetime_timezone.utc)


def legacy_migration_started_at():
    return _timestamp('DEVICE_LEGACY_MIGRATION_STARTED_AT')


def legacy_migration_deadline():
    return _timestamp('DEVICE_LEGACY_MIGRATION_DEADLINE')


def legacy_cohort_eligible(*, created_at, now=None) -> bool:
    if created_at is None:
        return False
    started_at = legacy_migration_started_at()
    if started_at is None:
        return not bool(getattr(settings, 'DJANGO_PRODUCTION', False))
    current = now or timezone.now()
    return current >= started_at and created_at <= started_at


def legacy_window_open(flag_name: str, *, now=None) -> bool:
    if not bool(getattr(settings, flag_name, False)):
        return False
    started_at = legacy_migration_started_at()
    deadline = legacy_migration_deadline()
    if deadline is None:
        # Local development and existing unit tests may deliberately exercise
        # a legacy path without production rollout configuration.
        return not bool(getattr(settings, 'DJANGO_PRODUCTION', False))
    current = now or timezone.now()
    if started_at is None:
        return not bool(getattr(settings, 'DJANGO_PRODUCTION', False)) and current < deadline
    return started_at <= current < deadline


def legacy_pos_migration_enabled(*, now=None) -> bool:
    return legacy_window_open('DEVICE_LEGACY_POS_MIGRATION_ENABLED', now=now)


def legacy_unbound_pos_session_auth_enabled(*, now=None) -> bool:
    return legacy_window_open('DEVICE_LEGACY_POS_SESSION_AUTH_ENABLED', now=now)


def legacy_local_agent_migration_enabled(*, now=None) -> bool:
    return legacy_window_open('DEVICE_LEGACY_LOCAL_AGENT_MIGRATION_ENABLED', now=now)


def legacy_local_agent_auth_enabled(*, now=None) -> bool:
    return legacy_window_open('DEVICE_LEGACY_LOCAL_AGENT_AUTH_ENABLED', now=now)


def legacy_tv_pairing_enabled(*, now=None) -> bool:
    return legacy_window_open('DEVICE_LEGACY_TV_PAIRING_ENABLED', now=now)


def legacy_tv_migration_enabled(*, now=None) -> bool:
    return legacy_window_open('DEVICE_LEGACY_TV_MIGRATION_ENABLED', now=now)


def pos_device_proof_required(*, now=None) -> bool:
    if bool(getattr(settings, 'DEVICE_POS_PROOF_REQUIRED', False)):
        return True
    if not bool(getattr(settings, 'DJANGO_PRODUCTION', False)) and legacy_migration_deadline() is None:
        return False
    return not legacy_pos_migration_enabled(now=now)
