import secrets
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.kitchen.models import TvMonitorDevice, TvMonitorPairing
from apps.kitchen.models.tv_monitor import hash_tv_monitor_secret
from apps.restaurants.models import Restaurant


TV_MONITOR_PAIRING_TTL = timedelta(minutes=10)


class TvMonitorPairingError(Exception):
    pass


class TvMonitorPairingExpired(TvMonitorPairingError):
    pass


class TvMonitorPairingRequired(TvMonitorPairingError):
    pass


def _new_secret() -> str:
    return secrets.token_urlsafe(32)


def restaurant_auth_code_hash(restaurant: Restaurant) -> str:
    return hash_tv_monitor_secret(restaurant.auth_code)


def create_tv_monitor_pairing(*, now=None):
    created_at = now or timezone.now()
    poll_token = _new_secret()
    claim_token = _new_secret()
    pairing = TvMonitorPairing.objects.create(
        poll_token_hash=hash_tv_monitor_secret(poll_token),
        claim_token_hash=hash_tv_monitor_secret(claim_token),
        expires_at=created_at + TV_MONITOR_PAIRING_TTL,
    )
    return pairing, poll_token, claim_token


def get_tv_monitor_pairing(*, pairing_id, poll_token: str, now=None) -> TvMonitorPairing:
    pairing = TvMonitorPairing.objects.select_related('device__restaurant').filter(pk=pairing_id).first()
    if pairing is None or not secrets.compare_digest(pairing.poll_token_hash, hash_tv_monitor_secret(poll_token)):
        raise TvMonitorPairingError('Pairing session is invalid.')
    if pairing.expires_at <= (now or timezone.now()) and pairing.device_id is None:
        raise TvMonitorPairingExpired('Pairing session has expired.')
    return pairing


@transaction.atomic
def claim_tv_monitor_pairing(*, pairing_id, claim_token: str, restaurant: Restaurant, now=None):
    claimed_at = now or timezone.now()
    pairing = TvMonitorPairing.objects.select_for_update().filter(pk=pairing_id).first()
    if pairing is None or not secrets.compare_digest(pairing.claim_token_hash, hash_tv_monitor_secret(claim_token)):
        raise TvMonitorPairingError('Pairing session is invalid.')
    if pairing.expires_at <= claimed_at:
        raise TvMonitorPairingExpired('Pairing session has expired.')
    if pairing.device_id is not None:
        return pairing.device

    if not restaurant.is_active:
        raise TvMonitorPairingError('Restaurant is inactive.')

    device = TvMonitorDevice.objects.create(
        restaurant=restaurant,
        token_hash=pairing.poll_token_hash,
        restaurant_auth_code_hash=restaurant_auth_code_hash(restaurant),
        paired_at=claimed_at,
    )
    pairing.device = device
    pairing.claimed_at = claimed_at
    pairing.save(update_fields=['device', 'claimed_at', 'updated_at'])
    return device


def authenticate_tv_monitor_device(*, token: str, now=None) -> TvMonitorDevice:
    authenticated_at = now or timezone.now()
    code_changed = False
    with transaction.atomic():
        device = (
            TvMonitorDevice.objects.select_for_update()
            .select_related('restaurant')
            .filter(token_hash=hash_tv_monitor_secret(token), revoked_at__isnull=True)
            .first()
        )
        if device is None or not device.restaurant.is_active:
            raise TvMonitorPairingRequired('TV pairing is required.')
        if not secrets.compare_digest(device.restaurant_auth_code_hash, restaurant_auth_code_hash(device.restaurant)):
            device.revoked_at = authenticated_at
            device.save(update_fields=['revoked_at', 'updated_at'])
            code_changed = True
        elif device.last_seen_at is None or device.last_seen_at < authenticated_at - timedelta(minutes=5):
            device.last_seen_at = authenticated_at
            device.save(update_fields=['last_seen_at', 'updated_at'])

    if code_changed:
        raise TvMonitorPairingRequired('Restaurant code changed. TV pairing is required.')
    return device
