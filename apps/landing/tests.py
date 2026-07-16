from unittest.mock import Mock, patch

from django.test import TestCase, override_settings
from django.urls import reverse


@override_settings(
    TELEGRAM_BOT_TOKEN='test-token',
    TELEGRAM_LEADS_CHAT_ID='-100000000',
    TELEGRAM_TIMEOUT=10.0,
    TELEGRAM_PROXY_URL='http://proxy.example:8000',
)
class LandingLeadViewTests(TestCase):
    @patch('apps.landing.api.views.httpx.Client')
    def test_submission_sends_formatted_telegram_message(self, client_mock):
        telegram_response = Mock()
        telegram_response.json.return_value = {'ok': True}
        telegram_client = client_mock.return_value.__enter__.return_value
        telegram_client.post.return_value = telegram_response

        response = self.client.post(
            reverse('landing-leads'),
            {
                'name': 'KEPuzChannel',
                'phone': '+98745632',
                'shop': 'archon1999',
                'plan': 'Umumiy',
            },
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 201)
        client_mock.assert_called_once_with(proxy='http://proxy.example:8000', timeout=10.0)
        payload = telegram_client.post.call_args.kwargs['json']
        self.assertEqual(payload['chat_id'], '-100000000')
        self.assertEqual(payload['parse_mode'], 'HTML')
        self.assertIn('<b>🔥 Yangi murojaat — PosCode FastFOOD</b>', payload['text'])
        self.assertIn('👤 <b>Ism:</b> KEPuzChannel', payload['text'])
        self.assertIn('📞 <b>Telefon:</b> +98745632', payload['text'])
        self.assertIn('🏪 <b>Shaxobcha:</b> archon1999', payload['text'])
        self.assertIn('📦 <b>Tarif:</b> Umumiy', payload['text'])
        self.assertRegex(payload['text'], r'🕒 <b>Vaqt:</b> \d{2}/\d{2}/\d{4}, \d{2}:\d{2}:\d{2}')

    @override_settings(TELEGRAM_BOT_TOKEN='', TELEGRAM_LEADS_CHAT_ID='')
    def test_submission_fails_safely_when_telegram_is_not_configured(self):
        response = self.client.post(
            reverse('landing-leads'),
            {'name': 'Aziz', 'phone': '+998901234567'},
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {'ok': False})
