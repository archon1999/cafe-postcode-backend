import os
from unittest.mock import Mock, patch

import httpx
from django.test import SimpleTestCase

from apps.platform.services.faktura import FakturaClient, FakturaError


class FakturaClientTests(SimpleTestCase):
    @patch.dict(
        os.environ,
        {
            'FAKTURA_TOKEN_URL': 'https://account.faktura.uz/token',
            'FAKTURA_API_BASE_URL': 'https://api.faktura.uz',
            'FAKTURA_USERNAME': 'user@example.com',
            'FAKTURA_PASSWORD': 'secret',
            'FAKTURA_CLIENT_ID': 'client-id',
            'FAKTURA_CLIENT_SECRET': 'client-secret',
            'FAKTURA_TIMEOUT': '12',
        },
        clear=False,
    )
    @patch('apps.platform.services.faktura.httpx.get')
    @patch('apps.platform.services.faktura.httpx.post')
    def test_lookup_sends_documented_auth_fields_and_company_inn_param(self, post_mock, get_mock):
        token_response = Mock()
        token_response.raise_for_status.return_value = None
        token_response.json.return_value = {'access_token': 'token-123'}
        post_mock.return_value = token_response

        lookup_response = Mock()
        lookup_response.raise_for_status.return_value = None
        lookup_response.json.return_value = {'CompanyInn': '123456789', 'CompanyName': 'Acme'}
        get_mock.return_value = lookup_response

        payload = FakturaClient().lookup_company_basic_details('123456789')

        self.assertEqual(payload['CompanyName'], 'Acme')
        post_mock.assert_called_once_with(
            'https://account.faktura.uz/token',
            data={
                'grant_type': 'password',
                'username': 'user@example.com',
                'password': 'secret',
                'client_id': 'client-id',
                'client_secret': 'client-secret',
            },
            timeout=12.0,
        )
        get_mock.assert_called_once_with(
            'https://api.faktura.uz/Api/Company/GetCompanyBasicDetails',
            params={'companyInn': '123456789'},
            headers={'Authorization': 'Bearer token-123'},
            timeout=12.0,
        )

    @patch.dict(
        os.environ,
        {
            'FAKTURA_USERNAME': 'user@example.com',
            'FAKTURA_PASSWORD': 'secret',
        },
        clear=False,
    )
    @patch('apps.platform.services.faktura.httpx.post')
    def test_auth_failures_are_wrapped_in_faktura_error(self, post_mock):
        post_mock.side_effect = httpx.RequestError('network down')

        with self.assertRaisesMessage(FakturaError, 'Failed to authenticate with Faktura.'):
            FakturaClient().lookup_company_basic_details('123456789')

    @patch.dict(
        os.environ,
        {
            'FAKTURA_USERNAME': 'user@example.com',
            'FAKTURA_PASSWORD': 'secret',
        },
        clear=False,
    )
    @patch('apps.platform.services.faktura.httpx.get')
    @patch('apps.platform.services.faktura.httpx.post')
    def test_lookup_failures_are_wrapped_in_faktura_error(self, post_mock, get_mock):
        token_response = Mock()
        token_response.raise_for_status.return_value = None
        token_response.json.return_value = {'access_token': 'token-123'}
        post_mock.return_value = token_response

        get_mock.side_effect = httpx.RequestError('lookup down')

        with self.assertRaisesMessage(FakturaError, 'Failed to fetch company details from Faktura.'):
            FakturaClient().lookup_company_basic_details('123456789')
