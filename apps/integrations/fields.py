import base64
import hashlib
import json

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import models


ENCRYPTED_JSON_PREFIX = 'enc:v1:'


def _integration_keys() -> list[str]:
    configured = getattr(settings, 'INTEGRATION_FERNET_KEYS', [])
    if isinstance(configured, str):
        configured = [value.strip() for value in configured.split(',') if value.strip()]
    keys = [str(value).strip() for value in configured if str(value).strip()]
    if not keys:
        if getattr(settings, 'DJANGO_PRODUCTION', False):
            raise ImproperlyConfigured(
                'INTEGRATION_FERNET_KEYS must contain at least one dedicated Fernet key in production.'
            )
        # Development/test compatibility only. Production validation requires a
        # dedicated rotatable key and never falls back to SECRET_KEY.
        digest = hashlib.sha256(f'integration-settings:v1:{settings.SECRET_KEY}'.encode()).digest()
        keys = [base64.urlsafe_b64encode(digest).decode('ascii')]
    return keys


def integration_cipher() -> MultiFernet:
    try:
        return MultiFernet([Fernet(key.encode('ascii')) for key in _integration_keys()])
    except (TypeError, ValueError) as error:
        raise ImproperlyConfigured(
            'Every INTEGRATION_FERNET_KEYS value must be a valid Fernet key.'
        ) from error


def encrypt_json(value, *, encoder=None) -> str:
    serialized = json.dumps(
        value,
        cls=encoder,
        ensure_ascii=False,
        separators=(',', ':'),
        sort_keys=True,
    ).encode('utf-8')
    return ENCRYPTED_JSON_PREFIX + integration_cipher().encrypt(serialized).decode('ascii')


def decrypt_json(value: str, *, decoder=None):
    token = value[len(ENCRYPTED_JSON_PREFIX) :]
    try:
        raw = integration_cipher().decrypt(token.encode('ascii'))
        return json.loads(raw.decode('utf-8'), cls=decoder)
    except (InvalidToken, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError('Stored integration settings cannot be decrypted.') from error


class EncryptedJSONField(models.JSONField):
    """JSON-compatible value encrypted as one authenticated Fernet envelope."""

    description = 'Encrypted JSON object'

    def from_db_value(self, value, expression, connection):
        value = super().from_db_value(value, expression, connection)
        if isinstance(value, str) and value.startswith(ENCRYPTED_JSON_PREFIX):
            return decrypt_json(value, decoder=self.decoder)
        return value

    def get_db_prep_value(self, value, connection, prepared=False):
        if hasattr(value, 'as_sql'):
            return value
        if not prepared:
            value = self.get_prep_value(value)
        if value is None:
            return super().get_db_prep_value(value, connection, prepared=True)
        if not (isinstance(value, str) and value.startswith(ENCRYPTED_JSON_PREFIX)):
            value = encrypt_json(value, encoder=self.encoder)
        return super().get_db_prep_value(value, connection, prepared=True)
