from unittest.mock import patch
from django.core.cache import cache
from django.test import SimpleTestCase
from apps.catalog_assistant.mxik import search_mxik


class MxikTests(SimpleTestCase):
    def setUp(self):
        cache.clear()

    @patch('apps.catalog_assistant.mxik.httpx.get')
    def test_name_search_uses_main_catalog_not_symbol_suggestions(self, get):
        get.return_value.json.return_value = {'data': {'content': [
            {'mxikCode': '10202001010000001', 'mxikName': 'Choy'},
            {'mxikCode': '10202001010000001', 'mxikName': 'Choy'},
        ]}}
        self.assertEqual(search_mxik('choy'), [{'code': '10202001010000001', 'name': 'Choy'}])
        self.assertEqual(get.call_args.kwargs['params']['text'], 'choy')
        self.assertTrue(get.call_args.args[0].endswith('/mxik/search/by-params'))
        search_mxik('choy')
        get.assert_called_once()
