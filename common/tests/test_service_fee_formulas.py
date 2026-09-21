import unittest

from common.service_fee_formulas import FormulaError, compile_formula, evaluate_formula
from common.service_fee_formulas.catalog import TEMPLATES, normalize_definition
from common.tests.service_fee_formula_cases import CASES


CONTEXT = {'subtotal': 500000, 'started_at': '2026-09-21T17:30:00+05:00',
           'calculated_at': '2026-09-21T18:30:00+05:00', 'guest_count': 2}


class FormulaLanguageTests(unittest.TestCase):
    def fee(self, source, parameters=None, **overrides):
        return evaluate_formula(source, parameters, **{**CONTEXT, **overrides})['amount']

    def test_technical_program_and_expression_are_equivalent(self):
        source = '''// Specialist-authored formula
let day_rate = 60000;
let night_rate = 120000;
let day = minutes_in(session.started_at, calculation.at, "09:00", "18:00");
let night = minutes_in("18:00", "09:00");
return round(day / 60 * day_rate + night / 60 * night_rate, 1000);
'''
        self.assertEqual(self.fee(source), 90000)

    def test_exact_money_and_final_rounding(self):
        self.assertEqual(self.fee('0.1 + 0.2 + 0.2'), 1)
        self.assertEqual(self.fee('round_money(16500, 1000, "half_down")'), 16000)
        self.assertEqual(self.fee('round_money(16500, 1000, "half_up")'), 17000)
        self.assertEqual(self.fee('(1 / 3 + 1 / 3 + 1 / 3) * 60000'), 60000)
        self.assertEqual(self.fee('abs(round(-16500, 1000, "half_up"))'), 17000)

    def test_minimum_hour_is_different_from_every_started_hour(self):
        end = '2026-09-21T19:00:00+05:00'
        self.assertEqual(self.fee('max(60, duration_minutes) * 1000', calculated_at=end), 90000)
        self.assertEqual(self.fee('ceil(duration_minutes / 60) * 60000', calculated_at=end), 120000)

    def test_if_and_boolean_operators_short_circuit(self):
        self.assertEqual(self.fee('if(subtotal > 0 || 1 / 0 > 0, 100, 1 / 0)'), 100)
        self.assertEqual(self.fee('if(false && 1 / 0 > 0, 1 / 0, 200)'), 200)
        self.assertEqual(self.fee('if(!false && guest_count == 2, 100, 200)'), 100)

    def test_parameters_and_bindings_cannot_replace_context(self):
        for source, parameters in [('subtotal', {'subtotal': 2}), ('let subtotal = 2; return subtotal;', {}),
                                   ('let fee = 1; let fee = 2; return fee;', {}),
                                   ('price', {'price': True})]:
            with self.subTest(source=source, parameters=parameters), self.assertRaises(FormulaError):
                compile_formula(source, parameters)

    def test_rejects_code_and_unknown_or_mistyped_operations(self):
        for source in ['__import__("os")', 'fetch("https://example.com")', 'subtotal.constructor',
                       'while (true) {}', 'return [];', 'subtotal = 0', 'unknown + 1',
                       'if(1, 2, 3)', '"5" * 10', 'true + 1', 'minutes_in(9, 18)',
                       'round(1, "1000")', 'add_minutes(1, 60)', 'add_minutes(started_at, "60")',
                       'add_minutes(started_at)', 'add_minutes(started_at, 60)',
                       '1; 2', 'let x = x; return x;', '', '1e100',
                       'subtotal < "100"', 'let if = 1; return if;', 'let x = 1;', '1 +']:
            with self.subTest(source=source), self.assertRaises(FormulaError):
                compile_formula(source)

    def test_rejects_runtime_errors_instead_of_charging_zero(self):
        for source in ['1 / 0', '-1', '2147483648', 'round(1, 0)', 'round(1, 1, "unknown")',
                       'minutes_in("09:00", "09:00")', 'minutes_in("24:00", "09:00")']:
            with self.subTest(source=source), self.assertRaises(FormulaError):
                self.fee(source)

    def test_resource_limits(self):
        for source in ['(' * 40 + '1' + ')' * 40, '+'.join(['1'] * 100), '9' * 41, ' ' * 8001]:
            with self.subTest(source=source[:50]), self.assertRaises(FormulaError):
                compile_formula(source)
        with self.assertRaises(FormulaError):
            self.fee('duration_minutes', calculated_at='2028-01-01T00:00:00Z')

    def test_cross_midnight_and_multiple_days(self):
        self.assertEqual(self.fee('minutes_in("18:00", "09:00")',
                                 started_at='2026-09-21T23:30:00+05:00',
                                 calculated_at='2026-09-22T00:30:00+05:00'), 60)
        self.assertEqual(self.fee('minutes_in("09:00", "18:00")',
                                 started_at='2026-09-21T00:00:00+05:00',
                                 calculated_at='2026-09-23T00:00:00+05:00'), 1080)

    def test_time_windows_partition_duration_without_double_counting(self):
        source = 'minutes_in("09:00", "18:00") + minutes_in("18:00", "09:00") - duration_minutes'
        for end in ['2026-09-21T18:00:00+05:00', '2026-09-22T09:00:00+05:00',
                    '2026-09-23T14:25:43.123456+05:00']:
            self.assertEqual(self.fee(source, calculated_at=end), 0)

    def test_arrival_tariff_and_exclusive_end_boundary(self):
        source = 'if(time_in(started_at, "09:00", "18:00"), 60000, 120000)'
        self.assertEqual(self.fee(source), 60000)
        self.assertEqual(self.fee(source, started_at='2026-09-21T18:00:00+05:00'), 120000)

    def test_daylight_saving_counts_actual_elapsed_time(self):
        self.assertEqual(self.fee('minutes_in("00:00", "09:00")', timezone_name='America/New_York',
                                 started_at='2026-03-08T00:00:00-05:00',
                                 calculated_at='2026-03-08T09:00:00-04:00'), 480)

    def test_timestamps_must_be_valid_and_ordered(self):
        for start in ['2026-09-21T17:30:00', 'not-a-date', '2026-09-21T19:00:00+05:00', None]:
            with self.subTest(start=start), self.assertRaises(FormulaError):
                self.fee('1', started_at=start)

    def test_revision_changes_with_parameters_and_ignores_untrusted_ast(self):
        first = normalize_definition({'source': 'subtotal * rate', 'parameters': {'rate': '0.1'}})
        repeated = normalize_definition({**first, 'program': {'result': ['number', '0']}})
        changed = normalize_definition({**first, 'parameters': {'rate': '0.2'}})
        self.assertEqual(first, repeated)
        self.assertNotEqual(first['revision'], changed['revision'])

    def test_all_templates_compile_and_evaluate(self):
        for template in TEMPLATES:
            with self.subTest(template=template['id']):
                definition = normalize_definition(template)
                self.assertGreaterEqual(self.fee(definition['source'], definition['parameters']), 0)

    def test_first_hour_template_matches_conformance_rule(self):
        template = next(item for item in TEMPLATES if item['id'] == 'scheduled_first_hour')
        for case in CASES:
            if case['name'].startswith('first_hour_schedule_'):
                with self.subTest(case=case['name']):
                    self.assertEqual(self.fee(template['source'], template['parameters'],
                                              **case['context']), case['amount'])

    def test_time_dependency_includes_aliases(self):
        self.assertTrue(compile_formula('let m = duration_minutes; return m;')['time_dependent'])
        self.assertTrue(compile_formula('minutes_in("09:00", "18:00")')['time_dependent'])
        self.assertTrue(compile_formula('if(time_in(calculation.at, "09:00", "18:00"), 1, 2)')['time_dependent'])
        self.assertFalse(compile_formula('if(time_in(started_at, "09:00", "18:00"), 1, 2)')['time_dependent'])

    def test_cross_runtime_conformance_cases(self):
        for case in CASES:
            with self.subTest(case=case['name']):
                context = {**case.get('context', {}), 'timezone_name': case.get('timezone', 'Asia/Tashkent')}
                if case.get('error'):
                    with self.assertRaises(FormulaError):
                        self.fee(case['source'], case.get('parameters'), **context)
                else:
                    self.assertEqual(self.fee(case['source'], case.get('parameters'), **context), case['amount'])


if __name__ == '__main__':
    unittest.main()
