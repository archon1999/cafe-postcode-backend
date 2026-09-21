import json
from unittest.mock import patch

from django.test import SimpleTestCase

from apps.restaurants.services.service_fee_ai import FormulaAIUnavailable, generate_formula_draft
from common.service_fee_formulas import FormulaError, evaluate_formula


EAGER_FIRST_HOUR = '''let first_hour_rate = if(time_in(session.started_at,"09:00","18:00"),50000,100000);
let after_first_hour = add_minutes(session.started_at,60);
let day_minutes = minutes_in(after_first_hour,calculation.at,"09:00","18:00");
let night_minutes = minutes_in(after_first_hour,calculation.at,"18:00","09:00");
return round(first_hour_rate + if(duration_minutes <= 60,0,ceil(day_minutes/5)*50000/12 + ceil(night_minutes/5)*100000/12),1000);'''
GUARDED_FIRST_HOUR = EAGER_FIRST_HOUR.replace(
    'let day_minutes = minutes_in(after_first_hour,calculation.at,"09:00","18:00");',
    'let day_minutes = if(duration_minutes <= 60,0,minutes_in(after_first_hour,calculation.at,"09:00","18:00"));',
).replace(
    'let night_minutes = minutes_in(after_first_hour,calculation.at,"18:00","09:00");',
    'let night_minutes = if(duration_minutes <= 60,0,minutes_in(after_first_hour,calculation.at,"18:00","09:00"));',
)


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

    def test_eager_first_hour_bindings_are_not_returned_as_a_usable_ai_draft(self):
        with self.assertRaisesMessage(FormulaError, 'Session duration'):
            evaluate_formula(EAGER_FIRST_HOUR, {}, subtotal=500000,
                             started_at='2026-09-21T18:00:00+05:00',
                             calculated_at='2026-09-21T18:30:00+05:00')
        with self.assertRaisesMessage(FormulaAIUnavailable, 'seans sinovidan'):
            self.generate(source=EAGER_FIRST_HOUR, parameters=[])

    def test_guarded_first_hour_draft_preserves_minimum_and_five_minute_rounding(self):
        draft = self.generate(source=GUARDED_FIRST_HOUR, parameters=[])['definition']
        for start, end, amount in (
            ('18:00', '18:00', 100000), ('18:00', '18:30', 100000),
            ('17:45', '18:15', 50000), ('17:45', '18:45', 50000),
            ('17:45', '19:15', 100000), ('18:00', '19:01', 108000),
            ('08:30', '10:00', 125000),
        ):
            with self.subTest(start=start, end=end):
                result = evaluate_formula(draft['source'], draft['parameters'], subtotal=500000,
                                          started_at=f'2026-09-21T{start}:00+05:00',
                                          calculated_at=f'2026-09-21T{end}:00+05:00')
                self.assertEqual(result['amount'], amount)

    def test_runtime_validation_also_checks_later_arrival_hours(self):
        with self.assertRaisesMessage(FormulaAIUnavailable, '18:00'):
            self.generate(source='if(time_in(session.started_at,"18:00","19:00"),1/0,100)', parameters=[])

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
