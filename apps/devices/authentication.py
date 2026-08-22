import re
from datetime import timedelta

from django.core.cache import cache
from django.contrib.auth.models import AnonymousUser
from django.utils import timezone
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed

from apps.devices.crypto import device_request_message, sha256_hex, verify_signature
from apps.devices.models import Device, SecurityEvent
from apps.devices.security import record_security_event


DEVICE_PROOF_WINDOW_SECONDS = 300
DEVICE_PROOF_FAILURE_DEDUPLICATION_SECONDS = 60
NONCE_RE = re.compile(r'^[A-Za-z0-9_-]{22,128}$')


class DeviceAuthenticationFailed(AuthenticationFailed):
    def __init__(self, code: str, detail: str):
        super().__init__({'code': code, 'detail': detail}, code=code)


class DeviceLeaseRecoveryAuthentication(BaseAuthentication):
    """Authenticate one signed device proof while allowing lease recovery."""

    def authenticate(self, request):
        device = authenticate_device_request(request, allow_expired_lease=True)
        return AnonymousUser(), device

    def authenticate_header(self, request):
        return 'Device'


def _fail(*, code, detail, request, device=None, reason=''):
    if device is not None:
        failure_reason = reason or code
        record_security_event(
            event_type='DEVICE_PROOF_FAILED',
            # A rolling lease reaching its deadline is an expected recovery
            # condition, not evidence of an attack. The following signed
            # renewal recovers the ACTIVE device with the same key.
            severity=(
                SecurityEvent.Severity.MEDIUM
                if failure_reason == 'lease_expired'
                else SecurityEvent.Severity.HIGH
            ),
            request=request,
            device=device,
            result='DENIED',
            metadata={'reason': failure_reason, 'path': request.path[:500]},
            # Browser/network retry storms must not turn one authentication
            # failure into thousands of identical audit rows. Distinct
            # device, path, reason or client IP combinations remain visible.
            deduplicate_for_seconds=DEVICE_PROOF_FAILURE_DEDUPLICATION_SECONDS,
        )
    raise DeviceAuthenticationFailed(code, detail)


def _raw_body(request) -> bytes:
    django_request = getattr(request, '_request', request)
    return django_request.body or b''


def _request_target(request) -> str:
    django_request = getattr(request, '_request', request)
    return django_request.get_full_path()


def _reserve_nonce(*, namespace: str, nonce: str, fingerprint: str = '1') -> str:
    key = f'device-proof:{namespace}:{sha256_hex(nonce)}'
    if cache.add(key, fingerprint, timeout=DEVICE_PROOF_WINDOW_SECONDS * 2):
        return 'new'
    return 'same' if cache.get(key) == fingerprint else 'conflict'


def _nonce_available(*, namespace: str, nonce: str) -> bool:
    return _reserve_nonce(namespace=namespace, nonce=nonce) == 'new'


def pairing_nonce_available(*, pairing, nonce: str) -> bool:
    if not NONCE_RE.fullmatch(str(nonce or '')):
        return False
    return _nonce_available(namespace=f'pairing:{pairing.pk}', nonce=nonce)


def authenticate_device_request(
    request,
    *,
    expected_types=None,
    expected_device=None,
    allow_expired_lease: bool = False,
) -> Device:
    device_id = str(request.headers.get('X-Device-Id') or '').strip().lower()
    timestamp_text = str(request.headers.get('X-Device-Timestamp') or '').strip()
    nonce = str(request.headers.get('X-Device-Nonce') or '').strip()
    claimed_body_hash = str(request.headers.get('X-Device-Content-SHA256') or '').strip().lower()
    signature = str(request.headers.get('X-Device-Signature') or '').strip()
    if not all((device_id, timestamp_text, nonce, claimed_body_hash, signature)):
        _fail(
            code='device_required',
            detail='A paired device proof is required.',
            request=request,
            reason='missing_headers',
        )

    device = Device.objects.select_related('restaurant').filter(pk=device_id).first()
    if device is None:
        _fail(code='device_proof_invalid', detail='Device proof is invalid.', request=request, reason='unknown_device')
    if expected_device is not None and device.pk != expected_device.pk:
        _fail(
            code='device_proof_invalid',
            detail='Device proof does not match the authenticated session.',
            request=request,
            device=device,
            reason='session_device_mismatch',
        )
    if not device.is_active:
        _fail(
            code='device_revoked',
            detail='This device has been revoked.',
            request=request,
            device=device,
            reason='revoked',
        )
    if expected_types and device.type not in set(expected_types):
        _fail(
            code='device_proof_invalid',
            detail='This device is not valid for this application.',
            request=request,
            device=device,
            reason='device_type_mismatch',
        )

    try:
        timestamp = int(timestamp_text)
    except ValueError:
        _fail(
            code='device_proof_invalid',
            detail='Device proof is invalid.',
            request=request,
            device=device,
            reason='timestamp_format',
        )
    if str(timestamp) != timestamp_text or abs(int(timezone.now().timestamp()) - timestamp) > DEVICE_PROOF_WINDOW_SECONDS:
        _fail(
            code='device_proof_invalid',
            detail='Device proof is invalid.',
            request=request,
            device=device,
            reason='timestamp_window',
        )
    if not NONCE_RE.fullmatch(nonce):
        _fail(
            code='device_proof_invalid',
            detail='Device proof is invalid.',
            request=request,
            device=device,
            reason='nonce_format',
        )
    body_hash = sha256_hex(_raw_body(request))
    if body_hash != claimed_body_hash:
        _fail(
            code='device_proof_invalid',
            detail='Device proof is invalid.',
            request=request,
            device=device,
            reason='body_hash',
        )
    message = device_request_message(
        method=request.method,
        request_target=_request_target(request),
        device_id=device.pk,
        timestamp=timestamp,
        nonce=nonce,
        body_sha256=body_hash,
    )
    signature_valid = verify_signature(
        algorithm=device.public_key_algorithm,
        public_key=device.public_key,
        signature=signature,
        message=message,
    )
    # Rolling POS compatibility: the previously deployed PWA signed the
    # slashless system-status target before Django's APPEND_SLASH redirect.
    # Accept that exact canonical target during the cache rollout; all other
    # proof fields (device, timestamp, nonce and body hash) remain bound.
    if not signature_valid and request.path == '/api/v1/system/status/':
        request_target = _request_target(request)
        path, separator, query = request_target.partition('?')
        legacy_target = f'{path.rstrip("/")}{separator}{query}'
        legacy_message = device_request_message(
            method=request.method,
            request_target=legacy_target,
            device_id=device.pk,
            timestamp=timestamp,
            nonce=nonce,
            body_sha256=body_hash,
        )
        signature_valid = verify_signature(
            algorithm=device.public_key_algorithm,
            public_key=device.public_key,
            signature=signature,
            message=legacy_message,
        )
    if not signature_valid:
        _fail(
            code='device_proof_invalid',
            detail='Device proof is invalid.',
            request=request,
            device=device,
            reason='signature',
        )
    proof_fingerprint = sha256_hex(f'{message}\n{signature}')
    nonce_state = _reserve_nonce(
        namespace=f'device:{device.pk}',
        nonce=nonce,
        fingerprint=proof_fingerprint,
    )
    # Browsers, mobile WebViews and intermediary networks can retry an
    # identical safe request at the transport layer.  Accept only the exact
    # same signed GET/HEAD proof; a changed target/body/signature with the same
    # nonce and every mutation replay remain denied.
    identical_safe_transport_retry = (
        nonce_state == 'same' and request.method in {'GET', 'HEAD'}
    )
    if nonce_state != 'new' and not identical_safe_transport_retry:
        _fail(
            code='device_replay_detected',
            detail='Device proof was already used.',
            request=request,
            device=device,
            reason='nonce_replay',
        )
    if not allow_expired_lease and device.lease_expires_at <= timezone.now():
        _fail(
            code='device_lease_expired',
            detail='Device authorization lease has expired.',
            request=request,
            device=device,
            reason='lease_expired',
        )

    now = timezone.now()
    if device.last_seen_at is None or device.last_seen_at < now - timedelta(minutes=5):
        Device.objects.filter(pk=device.pk).update(last_seen_at=now, updated_at=now)
        device.last_seen_at = now
    request.device = device
    return device


def authenticate_device_websocket_scope(scope, *, expected_types=None) -> Device | None:
    headers = {
        key.decode('latin1').lower(): value.decode('latin1')
        for key, value in scope.get('headers', [])
    }
    device_id = headers.get('x-device-id', '').strip().lower()
    timestamp_text = headers.get('x-device-timestamp', '').strip()
    nonce = headers.get('x-device-nonce', '').strip()
    claimed_body_hash = headers.get('x-device-content-sha256', '').strip().lower()
    signature = headers.get('x-device-signature', '').strip()
    if not all((device_id, timestamp_text, nonce, claimed_body_hash, signature)):
        return None
    device = Device.objects.select_related('restaurant').filter(pk=device_id).first()
    if device is None or not device.is_active or device.lease_expires_at <= timezone.now():
        return None
    if expected_types and device.type not in set(expected_types):
        return None
    try:
        timestamp = int(timestamp_text)
    except ValueError:
        return None
    if str(timestamp) != timestamp_text or abs(int(timezone.now().timestamp()) - timestamp) > DEVICE_PROOF_WINDOW_SECONDS:
        return None
    if not NONCE_RE.fullmatch(nonce):
        return None
    body_hash = sha256_hex(b'')
    if claimed_body_hash != body_hash:
        return None
    path = str(scope.get('path') or '/')
    raw_query = scope.get('query_string', b'')
    if raw_query:
        path = f'{path}?{raw_query.decode("latin1")}'
    message = device_request_message(
        method='GET',
        request_target=path,
        device_id=device.pk,
        timestamp=timestamp,
        nonce=nonce,
        body_sha256=body_hash,
    )
    if not verify_signature(
        algorithm=device.public_key_algorithm,
        public_key=device.public_key,
        signature=signature,
        message=message,
    ):
        return None
    if not _nonce_available(namespace=f'device:{device.pk}', nonce=nonce):
        record_security_event(
            event_type='DEVICE_PROOF_REPLAY_DETECTED',
            severity=SecurityEvent.Severity.HIGH,
            device=device,
            result='DENIED',
            metadata={'surface': 'websocket'},
        )
        return None
    now = timezone.now()
    Device.objects.filter(pk=device.pk).update(last_seen_at=now, updated_at=now)
    device.last_seen_at = now
    return device
