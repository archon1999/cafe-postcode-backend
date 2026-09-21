import json
from unittest.mock import patch

from django.test import SimpleTestCase

from apps.restaurants.services.service_fee_ai import FormulaAIUnavailable, generate_formula_draft


class ServiceFeeAITests(SimpleTestCase):
    def generate(self, source='subtotal * percent / 100', parameters=None, questions=None):
        draft = {'name': 'Foizli tarif', 'source': source,
                 'parameters': parameters if parameters is not None else [{'name': 'percent', 'value': '10'}],
                 'explanation': 'Buyurtma summasidan o‘n foiz.', 'questions': questions or []}
        with patch('apps.restaurants.services.service_fee_ai.ai_configuration', return_value=('test-key', 'test-model')), \
                patch('apps.restaurants.services.service_fee_ai.ai_proxy_url', return_value=None), \
                patch('apps.restaurants.services.service_fee_ai.httpx.Client') as client:
            response = client.return_value.__enter__.return_value.post.return_value
            response.json.return_value = {'status': 'completed', 'output': [
                {'type': 'message', 'content': [{'type': 'output_text', 'text': json.dumps(draft)}]}]}
            result = generate_formula_draft('Buyurtma summasining 10 foizi.')
            payload = client.return_value.__enter__.return_value.post.call_args.kwargs['json']
            self.assertFalse(payload['store'])
            self.assertTrue(payload['text']['format']['strict'])
            return result

    def test_generated_source_is_compiled_before_returning(self):
        result = self.generate()
        self.assertEqual(result['definition']['parameters'], {'percent': '10'})
        self.assertEqual(result['definition']['program']['version'], 1)
        self.assertEqual(result['questions'], [])

    def test_arbitrary_code_and_unknown_variables_are_rejected(self):
        for source in ('__import__("os")', 'unknown * 10'):
            with self.subTest(source=source), self.assertRaises(FormulaAIUnavailable):
                self.generate(source=source)

    def test_ambiguity_returns_questions_without_a_zero_fee_placeholder(self):
        result = self.generate(source='', parameters=[], questions=['Soatlik narx qancha?'])
        self.assertIsNone(result['definition'])
        self.assertEqual(len(result['questions']), 1)

    def test_duplicate_parameter_names_are_rejected(self):
        with self.assertRaises(FormulaAIUnavailable):
            self.generate(parameters=[{'name': 'percent', 'value': '10'}, {'name': 'percent', 'value': '20'}])

    def test_unconfigured_provider_does_not_make_a_request(self):
        with patch('apps.restaurants.services.service_fee_ai.ai_configuration', return_value=('', '')), \
                patch('apps.restaurants.services.service_fee_ai.httpx.Client') as client:
            with self.assertRaises(FormulaAIUnavailable):
                generate_formula_draft('Ten percent')
            client.assert_not_called()
