import os
from typing import Any

import httpx


class FakturaError(Exception):
    pass


class FakturaClient:
    def __init__(self):
        self.token_url = os.getenv('FAKTURA_TOKEN_URL', 'https://account.faktura.uz/token')
        self.api_base_url = os.getenv('FAKTURA_API_BASE_URL', 'https://api.faktura.uz')
        self.username = os.getenv('FAKTURA_USERNAME', '')
        self.password = os.getenv('FAKTURA_PASSWORD', '')
        self.timeout = float(os.getenv('FAKTURA_TIMEOUT', '10'))

    def _get_token(self) -> str:
        if not self.username or not self.password:
            raise FakturaError('Faktura credentials are not configured.')

        response = httpx.post(
            self.token_url,
            data={'username': self.username, 'password': self.password},
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        token = payload.get('access_token') or payload.get('token')
        if not token:
            raise FakturaError('Faktura token response did not include an access token.')
        return token

    def lookup_company_basic_details(self, inn: str) -> dict[str, Any]:
        token = self._get_token()
        response = httpx.get(
            f'{self.api_base_url}/Api/Company/GetCompanyBasicDetails',
            params={'tin': inn},
            headers={'Authorization': f'Bearer {token}'},
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()
