import re
from datetime import datetime, timedelta, timezone as datetime_timezone

from django.utils import timezone
from django.utils.dateparse import parse_datetime


LEGACY_POS_BRIDGE_MAX_LIFETIME = timedelta(hours=24)
LEGACY_POS_BRIDGE_KEYS = frozenset(
    {
        'configured',
        'enabled',
        'failure',
        'sourceCommit',
        'builtAt',
        'notAfter',
        'lastSeenAt',
        'terminalCount',
    }
)
LEGACY_POS_BRIDGE_FAILURES = frozenset(
    {
        '',
        'bridge_not_configured',
        'source_commit_invalid',
        'build_timestamp_invalid',
        'bridge_deadline_invalid',
        'bridge_expired',
    }
)
SERVER_BRIDGE_FAILURE_MISSING = 'heartbeat_missing'
SERVER_BRIDGE_FAILURE_INVALID = 'heartbeat_invalid'
_SOURCE_COMMIT_PATTERN = re.compile(r'^[0-9a-f]{40}$')
_UTC_SECONDS_PATTERN = re.compile(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$')
_UTC_NANO_PATTERN = re.compile(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?Z$')


def _server_bridge_state(failure):
    return {
        'configured': False,
        'enabled': False,
        'failure': failure,
    }


def _parse_exact_utc(value, *, seconds_only):
    if not isinstance(value, str):
        return None
    pattern = _UTC_SECONDS_PATTERN if seconds_only else _UTC_NANO_PATTERN
    if not pattern.fullmatch(value):
        return None
    if seconds_only:
        try:
            return datetime.strptime(value, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=datetime_timezone.utc)
        except ValueError:
            return None
    parsed = parse_datetime(value)
    if parsed is None or timezone.is_naive(parsed):
        return None
    return parsed.astimezone(datetime_timezone.utc)


def sanitize_legacy_pos_bridge_heartbeat(value, *, received_at=None):
    """Return a strict, secret-free rollout signal or a fail-closed marker.

    This signal is deliberately non-authoritative: websocket authentication
    supplies the restaurant scope, and no restaurant/device/token value from
    the heartbeat is persisted here.
    """
    received_at = (received_at or timezone.now()).astimezone(datetime_timezone.utc)
    if value is None:
        return _server_bridge_state(SERVER_BRIDGE_FAILURE_MISSING)
    if not isinstance(value, dict) or set(value) - LEGACY_POS_BRIDGE_KEYS:
        return _server_bridge_state(SERVER_BRIDGE_FAILURE_INVALID)

    configured = value.get('configured')
    enabled = value.get('enabled')
    failure = value.get('failure')
    if type(configured) is not bool or type(enabled) is not bool or not isinstance(failure, str):
        return _server_bridge_state(SERVER_BRIDGE_FAILURE_INVALID)
    if failure not in LEGACY_POS_BRIDGE_FAILURES or len(failure) > 40:
        return _server_bridge_state(SERVER_BRIDGE_FAILURE_INVALID)
    if enabled and (not configured or failure):
        return _server_bridge_state(SERVER_BRIDGE_FAILURE_INVALID)
    if not enabled and configured and not failure:
        return _server_bridge_state(SERVER_BRIDGE_FAILURE_INVALID)
    if not configured and (enabled or failure != 'bridge_not_configured'):
        return _server_bridge_state(SERVER_BRIDGE_FAILURE_INVALID)

    source_commit = value.get('sourceCommit')
    built_at_text = value.get('builtAt')
    not_after_text = value.get('notAfter')
    built_at = _parse_exact_utc(built_at_text, seconds_only=True)
    not_after = _parse_exact_utc(not_after_text, seconds_only=True)
    if configured:
        if (
            not isinstance(source_commit, str)
            or not _SOURCE_COMMIT_PATTERN.fullmatch(source_commit)
            or built_at is None
            or not_after is None
            or not_after <= built_at
            or not_after > built_at + LEGACY_POS_BRIDGE_MAX_LIFETIME
        ):
            return _server_bridge_state(SERVER_BRIDGE_FAILURE_INVALID)
        # The backend clock is the rollout authority. A workstation clock
        # rollback cannot extend an already-expired compatibility artifact.
        if enabled and received_at >= not_after:
            return _server_bridge_state(SERVER_BRIDGE_FAILURE_INVALID)
        if failure == 'bridge_expired' and received_at < not_after:
            return _server_bridge_state(SERVER_BRIDGE_FAILURE_INVALID)
    elif any(item is not None for item in (source_commit, built_at_text, not_after_text)):
        return _server_bridge_state(SERVER_BRIDGE_FAILURE_INVALID)

    last_seen_text = value.get('lastSeenAt')
    terminal_count = value.get('terminalCount')
    if last_seen_text is None and terminal_count is not None:
        return _server_bridge_state(SERVER_BRIDGE_FAILURE_INVALID)
    if last_seen_text is not None:
        last_seen_at = _parse_exact_utc(last_seen_text, seconds_only=False)
        if (
            last_seen_at is None
            or last_seen_at > received_at + timedelta(minutes=5)
            or type(terminal_count) is not int
            or not 1 <= terminal_count <= 10_000
        ):
            return _server_bridge_state(SERVER_BRIDGE_FAILURE_INVALID)
        if configured and last_seen_at < built_at:
            return _server_bridge_state(SERVER_BRIDGE_FAILURE_INVALID)

    sanitized = {
        'configured': configured,
        'enabled': enabled,
        'failure': failure,
    }
    if configured:
        sanitized.update(
            {
                'sourceCommit': source_commit,
                'builtAt': built_at_text,
                'notAfter': not_after_text,
            }
        )
    if last_seen_text is not None:
        sanitized['lastSeenAt'] = last_seen_text
        sanitized['terminalCount'] = terminal_count
    return sanitized


def rollout_state_from_heartbeat(value, *, received_at=None):
    received_at = (received_at or timezone.now()).astimezone(datetime_timezone.utc)
    return {
        'receivedAt': received_at.isoformat().replace('+00:00', 'Z'),
        'legacyPosBridge': sanitize_legacy_pos_bridge_heartbeat(value, received_at=received_at),
    }


def legacy_pos_bridge_summary(agent):
    state = agent.rollout_state if isinstance(agent.rollout_state, dict) else {}
    bridge = state.get('legacyPosBridge') if isinstance(state.get('legacyPosBridge'), dict) else {}
    if (
        set(bridge) == {'configured', 'enabled', 'failure'}
        and bridge.get('configured') is False
        and bridge.get('enabled') is False
        and bridge.get('failure') in {SERVER_BRIDGE_FAILURE_MISSING, SERVER_BRIDGE_FAILURE_INVALID}
    ):
        sanitized = dict(bridge)
    else:
        sanitized = sanitize_legacy_pos_bridge_heartbeat(
            bridge if bridge else None,
            received_at=agent.last_seen_at or timezone.now(),
        )
    observed = bool(sanitized.get('lastSeenAt')) and int(sanitized.get('terminalCount') or 0) > 0
    capable = 'legacy_pos_bridge_bounded' in (agent.capabilities or [])
    return {
        **sanitized,
        'checkInObserved': observed,
        'capabilityReported': capable,
        'readyForPOSUpdate': bool(agent.is_online() and capable and sanitized.get('enabled') and observed),
    }
