import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.core.exceptions import ImproperlyConfigured


TOTP_PERIOD_SECONDS = 30
TOTP_DIGITS = 6
RECOVERY_CODE_ALPHABET = '23456789ABCDEFGHJKLMNPQRSTUVWXYZ'


def _cipher() -> MultiFernet:
    keys = getattr(settings, 'ADMIN_MFA_FERNET_KEYS', [])
    if not keys:
        raise ImproperlyConfigured('ADMIN_MFA_FERNET_KEYS must contain at least one dedicated Fernet key.')
    try:
        return MultiFernet([Fernet(key.encode('ascii')) for key in keys])
    except (TypeError, ValueError) as error:
        raise ImproperlyConfigured('ADMIN_MFA_FERNET_KEYS contains an invalid Fernet key.') from error


def encrypt_mfa_secret(secret: str) -> str:
    return _cipher().encrypt(secret.encode('ascii')).decode('ascii')


def decrypt_mfa_secret(encrypted_secret: str) -> str:
    try:
        return _cipher().decrypt(encrypted_secret.encode('ascii')).decode('ascii')
    except InvalidToken as error:
        raise ValueError('Stored MFA secret cannot be decrypted.') from error


def generate_totp_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode('ascii').rstrip('=')


def provisioning_uri(*, secret: str, username: str, issuer: str = 'Cafe Postcode') -> str:
    label = quote(f'{issuer}:{username}', safe='')
    return f'otpauth://totp/{label}?secret={secret}&issuer={quote(issuer, safe="")}&algorithm=SHA1&digits=6&period=30'


def totp_code(secret: str, counter: int) -> str:
    padded = secret.upper().ljust((len(secret) + 7) // 8 * 8, '=')
    key = base64.b32decode(padded, casefold=True)
    digest = hmac.new(key, struct.pack('>Q', counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    binary = struct.unpack('>I', digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(binary % (10**TOTP_DIGITS)).zfill(TOTP_DIGITS)


def totp_code_digest(secret: str, code: str) -> str:
    """Return a secret-keyed digest used to reject exact OTP reuse across counters."""
    normalized = ''.join(character for character in str(code) if character in '0123456789')
    padded = secret.upper().ljust((len(secret) + 7) // 8 * 8, '=')
    key = base64.b32decode(padded, casefold=True)
    return hmac.new(key, b'cafe-admin-totp-code-v1\x00' + normalized.encode('ascii'), hashlib.sha256).hexdigest()


def verify_totp(
    secret: str,
    code: str,
    *,
    now: int | None = None,
    last_counter: int | None = None,
    last_code_digest: str = '',
) -> int | None:
    normalized = ''.join(character for character in str(code) if character in '0123456789')
    if len(normalized) != TOTP_DIGITS:
        return None
    if last_code_digest and hmac.compare_digest(totp_code_digest(secret, normalized), last_code_digest):
        return None
    current_counter = int(now if now is not None else time.time()) // TOTP_PERIOD_SECONDS
    for counter in range(current_counter - 1, current_counter + 2):
        if last_counter is not None and counter <= last_counter:
            continue
        if hmac.compare_digest(totp_code(secret, counter), normalized):
            return counter
    return None


def generate_recovery_codes(count: int = 10) -> list[str]:
    return [
        '-'.join(
            ''.join(secrets.choice(RECOVERY_CODE_ALPHABET) for _ in range(4))
            for _ in range(3)
        )
        for _ in range(count)
    ]


def hash_recovery_codes(codes: list[str]) -> list[str]:
    return [make_password(normalize_recovery_code(code)) for code in codes]


def normalize_recovery_code(code: str) -> str:
    return ''.join(character for character in str(code).upper() if character.isalnum())


def consume_recovery_code(code: str, hashes: list[str]) -> tuple[bool, list[str]]:
    normalized = normalize_recovery_code(code)
    if not normalized:
        return False, hashes
    for index, encoded in enumerate(hashes):
        if check_password(normalized, encoded):
            return True, [value for position, value in enumerate(hashes) if position != index]
    return False, hashes
