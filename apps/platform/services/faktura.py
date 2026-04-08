from dataclasses import dataclass
from typing import Any

import httpx
from django.conf import settings


class FakturaError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class FakturaConfig:
    token_url: str
    api_base_url: str
    username: str
    password: str
    client_id: str
    client_secret: str
    timeout: float

    @classmethod
    def from_settings(cls) -> 'FakturaConfig':
        return cls(
            token_url=str(getattr(settings, 'FAKTURA_TOKEN_URL', 'https://account.faktura.uz/token')).strip(),
            api_base_url=str(getattr(settings, 'FAKTURA_API_BASE_URL', 'https://api.faktura.uz')).strip(),
            username=str(getattr(settings, 'FAKTURA_USERNAME', '')).strip(),
            password=str(getattr(settings, 'FAKTURA_PASSWORD', '')).strip(),
            client_id=str(getattr(settings, 'FAKTURA_CLIENT_ID', '')).strip(),
            client_secret=str(getattr(settings, 'FAKTURA_CLIENT_SECRET', '')).strip(),
            timeout=float(getattr(settings, 'FAKTURA_TIMEOUT', 10.0)),
        )

    def validate(self) -> None:
        required_fields = {
            'FAKTURA_USERNAME': self.username,
            'FAKTURA_PASSWORD': self.password,
            'FAKTURA_CLIENT_ID': self.client_id,
            'FAKTURA_CLIENT_SECRET': self.client_secret,
        }
        missing_fields = [key for key, value in required_fields.items() if not value]
        if missing_fields:
            missing = ', '.join(missing_fields)
            raise FakturaError(f'Faktura credentials are not configured: {missing}.')


class FakturaClient:
    def __init__(self, config: FakturaConfig | None = None):
        self.config = config or FakturaConfig.from_settings()

    def _get_token(self) -> str:
        self.config.validate()

        request_data = {
            'grant_type': 'password',
            'username': self.config.username,
            'password': self.config.password,
            'client_id': self.config.client_id,
            'client_secret': self.config.client_secret,
        }

        try:
            response = httpx.post(
                self.config.token_url,
                data=request_data,
                timeout=self.config.timeout,
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise FakturaError('Failed to authenticate with Faktura.') from error

        token = payload.get('access_token') or payload.get('token')
        if not token:
            raise FakturaError('Faktura token response did not include an access token.')
        return token

    def lookup_company_basic_details(self, inn: str) -> dict[str, Any]:
        normalized_inn = inn.strip()
        if not normalized_inn:
            raise FakturaError('INN is required for Faktura lookup.')

        token = self._get_token()
        try:
            response = httpx.get(
                f'{self.config.api_base_url}/Api/Company/GetCompanyBasicDetails',
                params={'companyInn': normalized_inn},
                headers={'Authorization': f'Bearer {token}'},
                timeout=self.config.timeout,
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise FakturaError('Failed to fetch company details from Faktura.') from error

        if not isinstance(payload, dict):
            raise FakturaError('Faktura company lookup returned an invalid response.')

        return payload
