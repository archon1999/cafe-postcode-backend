"""Templates are editable source, not special cases in the calculator."""

import hashlib
import json

from .language import FormulaError, VERSION, compile_formula, normalize_parameters
from .runtime import Evaluator


TEMPLATES = [
    {'id': 'prorated', 'name': 'Daqiqaga mutanosib', 'source': 'duration_minutes / 60 * hourly_rate',
     'parameters': {'hourly_rate': '60000'}},
    {'id': 'minimum_hour', 'name': 'Birinchi soat to‘liq, keyin mutanosib',
     'source': 'max(minimum_minutes, duration_minutes) / 60 * hourly_rate',
     'parameters': {'hourly_rate': '60000', 'minimum_minutes': '60'}},
    {'id': 'started_hour', 'name': 'Har boshlangan soat to‘liq',
     'source': 'ceil(duration_minutes / 60) * hourly_rate', 'parameters': {'hourly_rate': '60000'}},
    {'id': 'free_minutes', 'name': 'Dastlabki daqiqalar bepul',
     'source': 'max(0, duration_minutes - free_minutes) / 60 * hourly_rate',
     'parameters': {'hourly_rate': '60000', 'free_minutes': '15'}},
    {'id': 'mixed', 'name': 'Foiz va soatlik',
     'source': 'subtotal * percent / 100 + duration_minutes / 60 * hourly_rate',
     'parameters': {'percent': '10', 'hourly_rate': '60000'}},
    {'id': 'scheduled', 'name': 'Kunduzgi va kechki tarif',
     'source': 'let day = minutes_in("09:00", "18:00");\n'
               'let night = minutes_in("18:00", "09:00");\n'
               'return day / 60 * day_rate + night / 60 * night_rate;',
     'parameters': {'day_rate': '60000', 'night_rate': '120000'}},
    {'id': 'scheduled_first_hour', 'name': 'Birinchi soat kirish tarifida, keyin smena bo‘yicha',
     'source': 'let first_hour_rate = if(time_in(session.started_at, "09:00", "18:00"), day_rate, night_rate);\n'
               'let first_hour_end = add_minutes(session.started_at, 60);\n'
               'return first_hour_rate + if(duration_minutes <= 60, 0,\n'
               '  minutes_in(first_hour_end, calculation.at, "09:00", "18:00") / 60 * day_rate\n'
               '  + minutes_in(first_hour_end, calculation.at, "18:00", "09:00") / 60 * night_rate);',
     'parameters': {'day_rate': '50000', 'night_rate': '100000'}},
    {'id': 'arrival_rate', 'name': 'Kirish vaqtidagi tarif',
     'source': 'let rate = if(time_in(session.started_at, "09:00", "18:00"), day_rate, night_rate);\n'
               'return duration_minutes / 60 * rate;',
     'parameters': {'day_rate': '60000', 'night_rate': '120000'}},
    {'id': 'minimum_fee', 'name': 'Minimal xizmat haqi',
     'source': 'max(minimum_fee, subtotal * percent / 100)',
     'parameters': {'percent': '10', 'minimum_fee': '20000'}},
    {'id': 'legacy_hourly', 'name': 'Amaldagi soatlik: 60 daqiqa minimum, 5 daqiqalik qadam',
     'source': 'round_money(hourly_rate * max(60, floor(duration_minutes / 5) * 5) / 60, 1000, "half_down")',
     'parameters': {'hourly_rate': '100000'}},
]


def normalize_definition(value):
    """Return a versioned, content-addressed definition suitable for snapshots."""
    if not isinstance(value, dict):
        raise FormulaError('Formula definition must be an object.')
    if type(value.get('version', VERSION)) is not int or value.get('version', VERSION) != VERSION:
        raise FormulaError('Unsupported formula language version.')
    source = value.get('source')
    parameters = normalize_parameters(value.get('parameters'))
    program = compile_formula(source, parameters)
    name = value.get('name', 'Xizmat haqi')
    if not isinstance(name, str) or not name.strip() or len(name) > 120:
        raise FormulaError('Formula name must contain 1 to 120 characters.')
    timezone_name = value.get('timezone', 'Asia/Tashkent')
    # Validate time zone without accessing the database or executing the formula.
    Evaluator({}, subtotal=0, started_at='2026-01-01T00:00:00Z',
              calculated_at='2026-01-01T00:00:00Z', timezone_name=timezone_name)
    definition = {'version': VERSION, 'name': name.strip(), 'source': source.strip(),
                  'parameters': parameters, 'timezone': timezone_name}
    canonical = json.dumps(definition, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    definition['revision'] = hashlib.sha256(canonical.encode()).hexdigest()
    definition['program'] = program
    return definition
