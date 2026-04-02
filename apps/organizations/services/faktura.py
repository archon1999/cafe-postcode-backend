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
        self.client_id = os.getenv('FAKTURA_CLIENT_ID', '')
        self.client_secret = os.getenv('FAKTURA_CLIENT_SECRET', '')
        self.timeout = float(os.getenv('FAKTURA_TIMEOUT', '10'))

    def _get_token(self) -> str:
        if not self.username or not self.password:
            raise FakturaError('Faktura credentials are not configured.')

        request_data = {
            'grant_type': 'password',
            'username': self.username,
            'password': self.password,
        }
        if self.client_id:
            request_data['client_id'] = self.client_id
        if self.client_secret:
            request_data['client_secret'] = self.client_secret

        try:
            response = httpx.post(
                self.token_url,
                data=request_data,
                timeout=self.timeout,
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
                f'{self.api_base_url}/Api/Company/GetCompanyBasicDetails',
                params={'companyInn': normalized_inn},
                headers={'Authorization': f'Bearer {token}'},
                timeout=self.timeout,
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise FakturaError('Failed to fetch company details from Faktura.') from error

        if not isinstance(payload, dict):
            raise FakturaError('Faktura company lookup returned an invalid response.')

        return payload
