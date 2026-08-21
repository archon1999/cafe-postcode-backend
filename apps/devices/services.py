import secrets
from datetime import timedelta
from urllib.parse import urlencode

from django.conf import settings
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.devices.crypto import (
    pairing_key_proof_message,
    pairing_status_message,
    public_key_fingerprint,
    verify_signature,
)
from apps.devices.models import Device, DevicePairing, SecurityEvent, hash_device_secret
from apps.devices.security import record_security_event


PAIRING_TTL = timedelta(minutes=10)
DEVICE_LEASE_TTL = timedelta(hours=24)
PAIRING_PROOF_WINDOW_SECONDS = 300


class DevicePairingError(Exception):
    code = 'pairing_invalid'


class DevicePairingExpired(DevicePairingError):
    code = 'pairing_expired'


class DevicePairingConflict(DevicePairingError):
    code = 'pairing_conflict'


class DevicePairingReplay(DevicePairingConflict):
    code = 'pairing_replay'


class DeviceLeaseExpired(DevicePairingError):
    code = 'device_lease_expired'


CAPABILITIES_BY_TYPE = {
    Device.Type.POS_TERMINAL: ['pos'],
    Device.Type.LOCAL_AGENT: ['local_agent'],
    Device.Type.TV_MONITOR: ['tv_monitor'],
    Device.Type.CONTROL_DEVICE: ['control'],
}


def create_pairing(
    *,
    device_type: str,
    name: str,
    platform: str,
    app_version: str,
    public_key_algorithm: str,
    public_key: str,
    proof_nonce: str,
    proof_signature: str,
):
    fingerprint = public_key_fingerprint(algorithm=public_key_algorithm, public_key=public_key)
    proof_message = pairing_key_proof_message(nonce=proof_nonce, fingerprint=fingerprint)
    if not verify_signature(
        algorithm=public_key_algorithm,
        public_key=public_key,
        signature=proof_signature,
        message=proof_message,
    ):
        raise DevicePairingError('Public-key possession proof is invalid.')

    replay_cache_key = f'device-pairing-create:{fingerprint}:{hash_device_secret(proof_nonce)}'
    if not cache.add(replay_cache_key, '1', timeout=int(PAIRING_TTL.total_seconds()) * 2):
        record_security_event(
            event_type='DEVICE_PAIRING_REPLAY_DETECTED',
            severity=SecurityEvent.Severity.HIGH,
            result='DENIED',
            metadata={'deviceType': device_type, 'fingerprint': fingerprint},
        )
        raise DevicePairingReplay('Pairing key proof was already used.')

    now = timezone.now()
    poll_token = secrets.token_urlsafe(32)
    claim_token = secrets.token_urlsafe(32)
    with transaction.atomic():
        expired_ids = list(
            DevicePairing.objects.select_for_update()
            .filter(
                public_key_fingerprint=fingerprint,
                status=DevicePairing.Status.PENDING,
                expires_at__lte=now,
            )
            .values_list('pk', flat=True)
        )
        if expired_ids:
            DevicePairing.objects.filter(pk__in=expired_ids).update(
                status=DevicePairing.Status.EXPIRED,
                updated_at=now,
            )
        if Device.objects.filter(public_key_fingerprint=fingerprint).exists():
            raise DevicePairingConflict('This device key is already registered.')
        active_pairings = DevicePairing.objects.select_for_update().filter(
            public_key_fingerprint=fingerprint,
            status=DevicePairing.Status.PENDING,
        )
        if active_pairings.exists():
            # Browser POS and TV WebViews do not reliably retain the local
            # poll-token metadata across reloads/power loss. A fresh possession
            # proof from the same private key safely replaces only that key's
            # inaccessible pending request. Agent requests retain the stricter
            # duplicate-conflict rule.
            if device_type not in {Device.Type.POS_TERMINAL, Device.Type.TV_MONITOR}:
                raise DevicePairingConflict('This device key already has an active pairing request.')
            active_pairings.update(status=DevicePairing.Status.EXPIRED, updated_at=now)
        try:
            with transaction.atomic():
                pairing = DevicePairing.objects.create(
                    device_type=device_type,
                    requested_name=name,
                    platform=platform,
                    app_version=app_version,
                    public_key_algorithm=public_key_algorithm,
                    public_key=public_key,
                    public_key_fingerprint=fingerprint,
                    poll_token_hash=hash_device_secret(poll_token),
                    claim_token_hash=hash_device_secret(claim_token),
                    display_code=f'{secrets.randbelow(1_000_000):06d}',
                    expires_at=now + PAIRING_TTL,
                )
        except IntegrityError as error:
            raise DevicePairingConflict(
                'This device key already has an active pairing request.'
            ) from error
    base_url = str(getattr(settings, 'DEVICE_PAIRING_CLAIM_BASE_URL', '') or '').rstrip('/')
    fragment = urlencode(
        {
            'v': 1,
            'pairingId': pairing.id,
            'claimToken': claim_token,
        }
    )
    claim_url = f'{base_url}#{fragment}' if base_url else ''
    record_security_event(
        event_type='DEVICE_PAIRING_REQUESTED',
        severity=SecurityEvent.Severity.INFO,
        result='PENDING',
        metadata={
            'pairingId': str(pairing.id),
            'deviceType': pairing.device_type,
            'fingerprint': fingerprint,
        },
    )
    return pairing, poll_token, claim_token, claim_url


def get_pairing_status(
    *, pairing_id, poll_token: str, timestamp: int, nonce: str, signature: str, replay_guard
) -> DevicePairing:
    pairing = DevicePairing.objects.select_related('device__restaurant').filter(pk=pairing_id).first()
    if pairing is None or not secrets.compare_digest(pairing.poll_token_hash, hash_device_secret(poll_token)):
        raise DevicePairingError('Pairing request is invalid.')
    now = timezone.now()
    if pairing.expires_at <= now and pairing.status == DevicePairing.Status.PENDING:
        DevicePairing.objects.filter(pk=pairing.pk, status=DevicePairing.Status.PENDING).update(
            status=DevicePairing.Status.EXPIRED,
            updated_at=now,
        )
        raise DevicePairingExpired('Pairing request has expired.')
    now_timestamp = int(now.timestamp())
    if abs(now_timestamp - int(timestamp)) > PAIRING_PROOF_WINDOW_SECONDS:
        raise DevicePairingError('Pairing status proof timestamp is invalid.')
    message = pairing_status_message(
        pairing_id=pairing.id,
        timestamp=int(timestamp),
        nonce=nonce,
        poll_token=poll_token,
    )
    if not verify_signature(
        algorithm=pairing.public_key_algorithm,
        public_key=pairing.public_key,
        signature=signature,
        message=message,
    ):
        raise DevicePairingError('Pairing status proof is invalid.')
    if not replay_guard(pairing=pairing, nonce=nonce):
        raise DevicePairingConflict('Pairing status proof was already used.')
    return pairing


@transaction.atomic
def approve_pairing(
    *,
    pairing_id,
    claim_token: str,
    restaurant,
    approved_by,
    name: str = '',
    request=None,
) -> Device:
    now = timezone.now()
    pairing = DevicePairing.objects.select_for_update().filter(pk=pairing_id).first()
    if pairing is None or not secrets.compare_digest(pairing.claim_token_hash, hash_device_secret(claim_token)):
        raise DevicePairingError('Pairing request is invalid.')
    if pairing.expires_at <= now:
        raise DevicePairingExpired('Pairing request has expired.')
    if pairing.status != DevicePairing.Status.PENDING or pairing.device_id is not None:
        raise DevicePairingConflict('Pairing request was already resolved.')
    if Device.objects.filter(public_key_fingerprint=pairing.public_key_fingerprint).exists():
        raise DevicePairingConflict('This device key is already registered.')
    if pairing.device_type != Device.Type.CONTROL_DEVICE and restaurant is None:
        raise DevicePairingError('Restaurant is required for this device type.')
    if restaurant is not None and not restaurant.is_active:
        raise DevicePairingError('Restaurant is inactive.')

    try:
        device = Device.objects.create(
            restaurant=restaurant,
            type=pairing.device_type,
            name=(name or pairing.requested_name)[:255],
            platform=pairing.platform,
            app_version=pairing.app_version,
            public_key_algorithm=pairing.public_key_algorithm,
            public_key=pairing.public_key,
            public_key_fingerprint=pairing.public_key_fingerprint,
            capabilities=CAPABILITIES_BY_TYPE[pairing.device_type],
            paired_by=approved_by,
            paired_at=now,
            lease_expires_at=now + DEVICE_LEASE_TTL,
            last_seen_at=now,
        )
    except IntegrityError as error:
        raise DevicePairingConflict('An active device already occupies this device slot.') from error
    if device.type == Device.Type.LOCAL_AGENT:
        from apps.local_agents.models import LocalAgent, hash_agent_token

        agent = LocalAgent.objects.select_for_update().filter(restaurant=restaurant).first()
        if agent is None:
            agent = LocalAgent.objects.create(
                restaurant=restaurant,
                device=device,
                name=device.name,
                token_hash=hash_agent_token(f'retired_{secrets.token_urlsafe(32)}'),
                status=LocalAgent.Status.OFFLINE,
                version=device.app_version,
                capabilities=['local_http', 'printer', 'marta_discovery'],
                lan_endpoints=[],
                protocol_version=1,
                is_active=True,
                credential_migrated_at=now,
            )
        else:
            agent.device = device
            agent.name = device.name
            agent.version = device.app_version
            agent.is_active = True
            agent.credential_migrated_at = now
            agent.save(
                update_fields=['device', 'name', 'version', 'is_active', 'credential_migrated_at', 'updated_at']
            )
    pairing.status = DevicePairing.Status.APPROVED
    pairing.approved_by = approved_by
    pairing.approved_at = now
    pairing.device = device
    pairing.save(update_fields=['status', 'approved_by', 'approved_at', 'device', 'updated_at'])
    record_security_event(
        event_type='DEVICE_PAIRING_APPROVED',
        severity=SecurityEvent.Severity.MEDIUM,
        request=request,
        restaurant=restaurant,
        actor=approved_by,
        device=device,
        result='SUCCESS',
        metadata={'pairingId': str(pairing.id), 'deviceType': device.type},
    )
    return device


@transaction.atomic
def reject_pairing(*, pairing_id, claim_token: str, rejected_by, restaurant=None, request=None) -> DevicePairing:
    now = timezone.now()
    pairing = DevicePairing.objects.select_for_update().filter(pk=pairing_id).first()
    if pairing is None or not secrets.compare_digest(pairing.claim_token_hash, hash_device_secret(claim_token)):
        raise DevicePairingError('Pairing request is invalid.')
    if pairing.status != DevicePairing.Status.PENDING:
        raise DevicePairingConflict('Pairing request was already resolved.')
    pairing.status = DevicePairing.Status.REJECTED
    pairing.rejected_by = rejected_by
    pairing.rejected_at = now
    pairing.save(update_fields=['status', 'rejected_by', 'rejected_at', 'updated_at'])
    record_security_event(
        event_type='DEVICE_PAIRING_REJECTED',
        severity=SecurityEvent.Severity.LOW,
        request=request,
        restaurant=restaurant,
        actor=rejected_by,
        result='REJECTED',
        metadata={'pairingId': str(pairing.id), 'deviceType': pairing.device_type},
    )
    return pairing


@transaction.atomic
def renew_device_lease(*, device: Device, request=None) -> Device:
    now = timezone.now()
    device = Device.objects.select_for_update(of=('self',)).select_related('restaurant').get(pk=device.pk)
    if not device.is_active:
        raise DevicePairingError('Device is revoked.')
    recovered = device.lease_expires_at <= now
    device.lease_expires_at = now + DEVICE_LEASE_TTL
    device.last_seen_at = now
    device.save(update_fields=['lease_expires_at', 'last_seen_at', 'updated_at'])
    record_security_event(
        event_type='DEVICE_LEASE_RECOVERED' if recovered else 'DEVICE_LEASE_RENEWED',
        severity=SecurityEvent.Severity.MEDIUM if recovered else SecurityEvent.Severity.INFO,
        request=request,
        device=device,
        result='SUCCESS',
    )
    return device


@transaction.atomic
def revoke_device(*, device: Device, revoked_by, reason: str, request=None) -> Device:
    from apps.users.models import AuthSession

    now = timezone.now()
    device = Device.objects.select_for_update(of=('self',)).select_related('restaurant').get(pk=device.pk)
    if device.status != Device.Status.REVOKED:
        device.status = Device.Status.REVOKED
        device.revoked_at = now
        device.revoked_by = revoked_by
        device.revoke_reason = reason[:500]
        device.save(update_fields=['status', 'revoked_at', 'revoked_by', 'revoke_reason', 'updated_at'])
        AuthSession.objects.filter(device=device, status=AuthSession.Status.ACTIVE).update(
            status=AuthSession.Status.REVOKED,
            revoked_at=now,
            updated_at=now,
        )
        if device.type == Device.Type.POS_TERMINAL and device.restaurant_id is not None:
            restaurant_id = device.restaurant_id
            backend_device_id = device.pk

            def enqueue_pos_revoke():
                from apps.local_agents.services import enqueue_durable_terminal_revoke

                enqueue_durable_terminal_revoke(
                    restaurant_id=restaurant_id,
                    backend_device_id=backend_device_id,
                )

            transaction.on_commit(enqueue_pos_revoke)
        if device.type == Device.Type.LOCAL_AGENT:
            from asgiref.sync import async_to_sync
            from channels.layers import get_channel_layer
            from apps.local_agents.services import local_agent_group_name

            from apps.local_agents.models import LocalAgent

            agent = LocalAgent.objects.filter(device=device).only('id').first()
            if agent is not None:
                transaction.on_commit(
                    lambda: async_to_sync(get_channel_layer().group_send)(
                        local_agent_group_name(agent.pk),
                        {'type': 'device.revoked'},
                    )
                )
    record_security_event(
        event_type='DEVICE_REVOKED',
        severity=SecurityEvent.Severity.HIGH,
        request=request,
        actor=revoked_by,
        device=device,
        result='SUCCESS',
        metadata={'reason': reason[:500]},
    )
    return device
