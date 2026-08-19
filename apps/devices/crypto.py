import base64
import hashlib
import re

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

from apps.devices.models import Device


BASE64URL_RE = re.compile(r'^[A-Za-z0-9_-]+$')


class DeviceKeyError(ValueError):
    pass


def base64url_decode(value: str) -> bytes:
    normalized = str(value or '').strip()
    if not normalized or not BASE64URL_RE.fullmatch(normalized):
        raise DeviceKeyError('Value must be unpadded base64url.')
    try:
        return base64.urlsafe_b64decode(normalized + '=' * (-len(normalized) % 4))
    except (ValueError, TypeError) as error:
        raise DeviceKeyError('Value must be valid base64url.') from error


def public_key_bytes(*, algorithm: str, public_key: str) -> bytes:
    raw = base64url_decode(public_key)
    try:
        if algorithm == Device.PublicKeyAlgorithm.ED25519:
            if len(raw) != 32:
                raise DeviceKeyError('Ed25519 public key must contain 32 bytes.')
            ed25519.Ed25519PublicKey.from_public_bytes(raw)
            return raw
        if algorithm == Device.PublicKeyAlgorithm.P256_SHA256:
            loaded = serialization.load_der_public_key(raw)
            if not isinstance(loaded, ec.EllipticCurvePublicKey) or not isinstance(loaded.curve, ec.SECP256R1):
                raise DeviceKeyError('Public key must use the P-256 curve.')
            canonical = loaded.public_bytes(
                encoding=serialization.Encoding.DER,
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
            )
            if canonical != raw:
                raise DeviceKeyError('P-256 public key must be canonical DER SubjectPublicKeyInfo.')
            return raw
    except (ValueError, TypeError) as error:
        raise DeviceKeyError('Public key is invalid.') from error
    raise DeviceKeyError('Public-key algorithm is unsupported.')


def public_key_fingerprint(*, algorithm: str, public_key: str) -> str:
    return hashlib.sha256(public_key_bytes(algorithm=algorithm, public_key=public_key)).hexdigest()


def verify_signature(*, algorithm: str, public_key: str, signature: str, message: str) -> bool:
    try:
        raw_key = public_key_bytes(algorithm=algorithm, public_key=public_key)
        raw_signature = base64url_decode(signature)
        payload = message.encode('utf-8')
        if algorithm == Device.PublicKeyAlgorithm.ED25519:
            ed25519.Ed25519PublicKey.from_public_bytes(raw_key).verify(raw_signature, payload)
        elif algorithm == Device.PublicKeyAlgorithm.P256_SHA256:
            loaded = serialization.load_der_public_key(raw_key)
            if len(raw_signature) == 64:
                r = int.from_bytes(raw_signature[:32], 'big')
                s = int.from_bytes(raw_signature[32:], 'big')
                raw_signature = encode_dss_signature(r, s)
            loaded.verify(raw_signature, payload, ec.ECDSA(hashes.SHA256()))
        else:
            return False
        return True
    except (DeviceKeyError, InvalidSignature, ValueError, TypeError):
        return False


def sha256_hex(value: bytes | str) -> str:
    if isinstance(value, str):
        value = value.encode('utf-8')
    return hashlib.sha256(value).hexdigest()


def pairing_key_proof_message(*, nonce: str, fingerprint: str) -> str:
    return f'pairing-v1\n{nonce}\n{fingerprint}'


def pairing_status_message(*, pairing_id, timestamp: int, nonce: str, poll_token: str) -> str:
    return f'pairing-status-v1\n{str(pairing_id).lower()}\n{timestamp}\n{nonce}\n{sha256_hex(poll_token)}'


def device_request_message(
    *, method: str, request_target: str, device_id, timestamp: int, nonce: str, body_sha256: str
) -> str:
    return (
        f'v1\n{method.upper()}\n{request_target}\n{str(device_id).lower()}\n'
        f'{timestamp}\n{nonce}\n{body_sha256.lower()}'
    )


def pos_migration_attestation_message(attestation: dict) -> str:
    return '\n'.join(
        [
            'pos-migration-v1',
            str(attestation['restaurant_id']).lower(),
            str(attestation['local_agent_device_id']).lower(),
            str(attestation['terminal_id']),
            str(attestation['public_key_fingerprint']).lower(),
            str(int(attestation['issued_at'])),
            str(int(attestation['expires_at'])),
            str(attestation['nonce']),
        ]
    )

