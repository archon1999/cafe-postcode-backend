import base64
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from django.conf import settings


class QzTraySecurityService:
    def _read_value(self, *, inline: str, file_path: str, label: str) -> str:
        value = (inline or '').replace('\\n', '\n').strip()
        if value:
            return value

        path = (file_path or '').strip()
        if not path:
            raise ValueError(f'QZ Tray {label} is not configured.')

        content = Path(path).read_text(encoding='utf-8').strip()
        if not content:
            raise ValueError(f'QZ Tray {label} file is empty.')
        return content

    def certificate(self) -> str:
        return self._read_value(
            inline=getattr(settings, 'QZ_TRAY_CERTIFICATE_PEM', ''),
            file_path=getattr(settings, 'QZ_TRAY_CERTIFICATE_PATH', ''),
            label='certificate',
        )

    def sign(self, payload: str) -> str:
        private_key_pem = self._read_value(
            inline=getattr(settings, 'QZ_TRAY_PRIVATE_KEY_PEM', ''),
            file_path=getattr(settings, 'QZ_TRAY_PRIVATE_KEY_PATH', ''),
            label='private key',
        )
        password = (getattr(settings, 'QZ_TRAY_PRIVATE_KEY_PASSWORD', '') or '').encode('utf-8') or None
        key = serialization.load_pem_private_key(private_key_pem.encode('utf-8'), password=password)
        signature = key.sign(payload.encode('utf-8'), padding.PKCS1v15(), hashes.SHA512())
        return base64.b64encode(signature).decode('ascii')
