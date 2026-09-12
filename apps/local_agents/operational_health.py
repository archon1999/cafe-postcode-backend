"""Operational evidence only: connectivity, shifts and security are separate."""
from datetime import timedelta
from django.utils.dateparse import parse_datetime
from django.utils import timezone

FRESHNESS = timedelta(hours=24)
COMPONENTS = {'storage', 'runtime', 'pos_login', 'order_save', 'printer', 'payment', 'fiscal', 'sync'}
CRITICAL = {'storage', 'runtime', 'pos_login', 'order_save'}
INTEGRATION_COMPONENTS = {'printer', 'payment', 'fiscal'}


def _timestamp(value):
    try:
        return parse_datetime(str(value or ''))
    except (TypeError, ValueError, OverflowError):
        return None


def normalize_health(value, now):
    if not isinstance(value, dict) or value.get('schemaVersion') != 1:
        return None
    checked = _timestamp(value.get('checkedAt'))
    if checked is None or timezone.is_naive(checked) or checked > now + timedelta(minutes=1):
        return None
    checks = value.get('checks')
    if not isinstance(checks, list) or len(checks) > 128:
        return None
    normalized = []
    for check in checks:
        if not isinstance(check, dict) or check.get('component') not in COMPONENTS:
            return None
        if check.get('state') not in ('ok', 'error', 'unknown'):
            return None
        failures = check.get('consecutiveFailures', 0)
        if type(failures) is not int or not 0 <= failures <= 100000:
            return None
        normalized.append({
            'component': check['component'], 'resource': str(check.get('resource', ''))[:128],
            'state': check['state'], 'consecutiveFailures': failures,
            'confirmed': check.get('confirmed') is True,
        })
    return {'schemaVersion': 1, 'checkedAt': checked.isoformat(), 'receivedAt': now.isoformat(), 'checks': normalized}


def assess_operational_health(value, now):
    result = {'status': 'unknown', 'reasons': [], 'checkedAt': None, 'freshnessMinutes': int(FRESHNESS.total_seconds() // 60)}
    if not isinstance(value, dict) or value.get('schemaVersion') != 1:
        return result
    checked = _timestamp(value.get('checkedAt'))
    if checked is None or timezone.is_naive(checked):
        return result
    result['checkedAt'] = checked.isoformat()
    if now - checked > FRESHNESS or checked > now + timedelta(minutes=1):
        return result
    checks = value.get('checks', [])
    resources = {(c.get('component'), str(c.get('resource', ''))) for c in checks}
    checks = [
        c for c in checks
        if not (
            c.get('component') in INTEGRATION_COMPONENTS
            and not str(c.get('resource', '')).startswith('probe/')
            and (c.get('component'), f"probe/{c.get('resource', '')}") in resources
        )
    ]
    reasons = [c for c in checks if c.get('state') == 'error' and (
        c.get('consecutiveFailures', 0) >= 3 or (c.get('confirmed') and c.get('component') in ('storage', 'runtime'))
    )]
    if reasons:
        result['status'] = 'critical' if any(c['component'] in CRITICAL for c in reasons) else 'attention'
        result['reasons'] = reasons
    elif any(c.get('component') == 'storage' and c.get('state') == 'ok' for c in checks) and not any(c.get('state') == 'unknown' for c in checks):
        result['status'] = 'healthy'
    return result
