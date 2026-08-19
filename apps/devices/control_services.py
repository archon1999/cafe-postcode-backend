import secrets

from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

from apps.devices.control_serializers import CONTROL_DEVICE_TYPES
from apps.devices.models import DevicePairing, SecurityEvent, hash_device_secret
from apps.devices.security import record_security_event
from apps.devices.services import DevicePairingError, approve_pairing, reject_pairing


CONTROL_PAIRING_MAX_FAILURES = 5
CONTROL_PAIRING_FAILURE_TTL_SECONDS = 5 * 60


class ControlPairingInvalid(Exception):
    pass


class ControlPairingAttemptsExceeded(ControlPairingInvalid):
    pass


def _failure_key(pairing_id, phase: str) -> str:
    return f'control-pairing-failures:{phase}:{pairing_id}'


def pairing_failure_count(pairing_id, *, phase: str) -> int:
    return int(cache.get(_failure_key(pairing_id, phase), 0) or 0)


def reserve_control_pairing_attempt(pairing_id, *, phase: str) -> int:
    """Atomically reserve one verification attempt before secret validation."""
    key = _failure_key(pairing_id, phase)
    cache.add(key, 0, timeout=CONTROL_PAIRING_FAILURE_TTL_SECONDS)
    try:
        failure_count = int(cache.incr(key))
    except (ValueError, TypeError) as error:
        # A backend without atomic increment cannot safely enforce this budget.
        cache.set(key, CONTROL_PAIRING_MAX_FAILURES + 1, timeout=CONTROL_PAIRING_FAILURE_TTL_SECONDS)
        raise ControlPairingAttemptsExceeded from error
    if failure_count > CONTROL_PAIRING_MAX_FAILURES:
        raise ControlPairingAttemptsExceeded
    return failure_count


def release_control_pairing_attempt(pairing_id, *, phase: str):
    """Release only this successful reservation; concurrent failures remain counted."""
    key = _failure_key(pairing_id, phase)
    try:
        remaining = int(cache.decr(key))
    except (ValueError, TypeError):
        return
    if remaining <= 0:
        cache.delete(key)


def record_control_pairing_failure(*, pairing_id, failure_count: int, request, restaurant=None) -> int:
    record_security_event(
        event_type=(
            'CONTROL_PAIRING_ATTEMPTS_EXCEEDED'
            if failure_count >= CONTROL_PAIRING_MAX_FAILURES
            else 'CONTROL_PAIRING_VERIFICATION_FAILED'
        ),
        severity=(
            SecurityEvent.Severity.HIGH
            if failure_count >= CONTROL_PAIRING_MAX_FAILURES
            else SecurityEvent.Severity.MEDIUM
        ),
        request=request,
        restaurant=restaurant,
        result='DENIED',
        metadata={
            'pairingId': str(pairing_id),
            'failureCount': failure_count,
        },
    )
    return failure_count


def clear_control_pairing_failures(pairing_id):
    cache.delete_many(
        (
            _failure_key(pairing_id, 'resolve'),
            _failure_key(pairing_id, 'decision'),
        )
    )


def _valid_pending_pairing(*, pairing, claim_token: str, display_code: str | None = None) -> bool:
    if pairing is None:
        return False
    if pairing.device_type not in CONTROL_DEVICE_TYPES:
        return False
    if pairing.status != DevicePairing.Status.PENDING or pairing.device_id is not None:
        return False
    if pairing.expires_at <= timezone.now():
        return False
    if not secrets.compare_digest(pairing.claim_token_hash, hash_device_secret(claim_token)):
        return False
    if display_code is not None and not secrets.compare_digest(pairing.display_code, display_code):
        return False
    return True


def resolve_control_pairing(*, pairing_id, claim_token: str) -> DevicePairing:
    pairing = DevicePairing.objects.filter(pk=pairing_id).first()
    if not _valid_pending_pairing(pairing=pairing, claim_token=claim_token):
        if pairing is not None and pairing.status == DevicePairing.Status.PENDING and pairing.expires_at <= timezone.now():
            DevicePairing.objects.filter(pk=pairing.pk, status=DevicePairing.Status.PENDING).update(
                status=DevicePairing.Status.EXPIRED,
                updated_at=timezone.now(),
            )
        raise ControlPairingInvalid
    return pairing


@transaction.atomic
def approve_control_pairing(
    *,
    pairing_id,
    claim_token: str,
    display_code: str,
    restaurant,
    approved_by,
    name: str,
    request=None,
) -> object:
    pairing = DevicePairing.objects.select_for_update().filter(pk=pairing_id).first()
    if (
        restaurant is None
        or not restaurant.is_active
        or not _valid_pending_pairing(
            pairing=pairing,
            claim_token=claim_token,
            display_code=display_code,
        )
    ):
        raise ControlPairingInvalid
    try:
        device = approve_pairing(
            pairing_id=pairing_id,
            claim_token=claim_token,
            restaurant=restaurant,
            approved_by=approved_by,
            name=name,
            request=request,
        )
    except DevicePairingError as error:
        raise ControlPairingInvalid from error
    clear_control_pairing_failures(pairing_id)
    return device


@transaction.atomic
def reject_control_pairing(
    *,
    pairing_id,
    claim_token: str,
    display_code: str,
    restaurant,
    rejected_by,
    request=None,
) -> DevicePairing:
    pairing = DevicePairing.objects.select_for_update().filter(pk=pairing_id).first()
    if (
        restaurant is None
        or not restaurant.is_active
        or not _valid_pending_pairing(
            pairing=pairing,
            claim_token=claim_token,
            display_code=display_code,
        )
    ):
        raise ControlPairingInvalid
    try:
        pairing = reject_pairing(
            pairing_id=pairing_id,
            claim_token=claim_token,
            rejected_by=rejected_by,
            restaurant=restaurant,
            request=request,
        )
    except DevicePairingError as error:
        raise ControlPairingInvalid from error
    clear_control_pairing_failures(pairing_id)
    return pairing
