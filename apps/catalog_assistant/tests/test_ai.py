import json
from unittest.mock import patch
from django.test import SimpleTestCase
from apps.catalog_assistant.ai import extract_menu, CatalogAIUnavailable


class AITests(SimpleTestCase):
    def response(self, rows, status='completed'):
        return {'status': status, 'output': [{'type': 'message', 'content': [
            {'type': 'output_text', 'text': json.dumps({'rows': rows})}]}]}

    def row(self):
        return {'name': 'Choy', 'name_ru': '', 'category_name': '', 'price': None,
                'sale_unit': 'piece', 'description': '', 'evidence': 'Choy ?', 'warning': 'Narx topilmadi'}

    @patch('apps.catalog_assistant.ai.ai_proxy_url', return_value=None)
    @patch('apps.catalog_assistant.ai.ai_configuration', return_value=('test-key', 'gpt-5.6-luna'))
    @patch('apps.catalog_assistant.ai.httpx.Client')
    def test_image_and_text_use_existing_model_and_strict_review_schema(self, client, config, proxy):
        response = client.return_value.__enter__.return_value.post.return_value
        response.json.return_value = self.response([self.row()])
        content = [{'type': 'input_text', 'text': 'Choy ?'}, {'type': 'input_image', 'image_url': 'data:image/jpeg;base64,test'}]
        result = extract_menu(content, ['Ichimliklar'])
        payload = client.return_value.__enter__.return_value.post.call_args.kwargs['json']
        self.assertEqual(payload['input'][0]['content'], content)
        self.assertEqual(payload['model'], 'gpt-5.6-luna')
        self.assertFalse(payload['store'])
        self.assertTrue(payload['text']['format']['strict'])
        self.assertIsNone(result[0]['price'])

    @patch('apps.catalog_assistant.ai.ai_proxy_url', return_value=None)
    @patch('apps.catalog_assistant.ai.ai_configuration', return_value=('test-key', 'gpt-5.6-luna'))
    @patch('apps.catalog_assistant.ai.httpx.Client')
    def test_invalid_incomplete_refused_or_excessive_output_never_becomes_draft(self, client, config, proxy):
        response = client.return_value.__enter__.return_value.post.return_value
        for payload in [self.response([], 'incomplete'), self.response([]), self.response([self.row()] * 101),
                        self.response([{**self.row(), 'price': -1}]), self.response([{**self.row(), 'sale_unit': 'unknown'}]),
                        {'status': 'completed', 'output': [{'type': 'message', 'content': [{'type': 'refusal', 'refusal': 'no'}]}]}]:
            with self.subTest(payload=payload):
                response.json.return_value = payload
                with self.assertRaises(CatalogAIUnavailable):
                    extract_menu([{'type': 'input_text', 'text': 'source'}], [])
