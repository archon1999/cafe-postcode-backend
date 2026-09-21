"""Hand-calculated conformance cases shared with the offline evaluator."""

CONTEXT = {'subtotal': 500000, 'started_at': '2026-09-21T17:30:00+05:00',
           'calculated_at': '2026-09-21T18:30:00+05:00', 'guest_count': 2}
FIRST_HOUR_SOURCE = '''let first_hour_rate = if(time_in(session.started_at, "09:00", "18:00"), day_rate, night_rate);
let first_hour_end = add_minutes(session.started_at, 60);
return first_hour_rate + if(duration_minutes <= 60, 0,
  minutes_in(first_hour_end, calculation.at, "09:00", "18:00") / 60 * day_rate
  + minutes_in(first_hour_end, calculation.at, "18:00", "09:00") / 60 * night_rate);'''

CASES = [
    {'name': 'percentage', 'source': 'subtotal * percent / 100', 'parameters': {'percent': '7.5'}, 'amount': 37500},
    {'name': 'exact_fraction', 'source': '(1 / 3 + 1 / 3 + 1 / 3) * 60000', 'amount': 60000},
    {'name': 'half_up', 'source': '0.1 + 0.2 + 0.2', 'amount': 1},
    {'name': 'half_down', 'source': 'round(16500, 1000, "half_down")', 'amount': 16000},
    {'name': 'negative_rounding', 'source': 'abs(round(-16500, 1000, "half_up"))', 'amount': 17000},
    {'name': 'negative_floor', 'source': 'abs(floor(-1.1))', 'amount': 2},
    {'name': 'negative_ceil', 'source': 'abs(ceil(-1.1))', 'amount': 1},
    {'name': 'remainder_truncates', 'source': 'abs(-5 % 3)', 'amount': 2},
    {'name': 'first_hour', 'source': 'max(60, duration_minutes) * 1000',
     'context': {'calculated_at': '2026-09-21T18:00:00+05:00'}, 'amount': 60000},
    {'name': 'prorated', 'source': 'duration_minutes * 1000',
     'context': {'calculated_at': '2026-09-21T18:00:00+05:00'}, 'amount': 30000},
    {'name': 'started_hour', 'source': 'ceil(duration_minutes / 60) * 60000',
     'context': {'calculated_at': '2026-09-21T19:00:00+05:00'}, 'amount': 120000},
    {'name': 'scheduled', 'source': 'let day = minutes_in("09:00", "18:00");\n'
                                  'let night = minutes_in(session.started_at, calculation.at, "18:00", "09:00");\n'
                                  'return day * day_rate / 60 + night * night_rate / 60;',
     'parameters': {'day_rate': '60000', 'night_rate': '120000'}, 'amount': 90000},
    {'name': 'arrival', 'source': 'if(time_in(started_at, "09:00", "18:00"), 60000, 120000)', 'amount': 60000},
    {'name': 'boundary', 'source': 'if(time_in(started_at, "09:00", "18:00"), 60000, 120000)',
     'context': {'started_at': '2026-09-21T18:00:00+05:00'}, 'amount': 120000},
    {'name': 'overnight', 'source': 'minutes_in("18:00", "09:00")',
     'context': {'started_at': '2026-09-21T23:30:00+05:00', 'calculated_at': '2026-09-22T00:30:00+05:00'}, 'amount': 60},
    {'name': 'multiple_days', 'source': 'minutes_in("09:00", "18:00")',
     'context': {'started_at': '2026-09-21T00:00:00+05:00', 'calculated_at': '2026-09-23T00:00:00+05:00'}, 'amount': 1080},
    {'name': 'zero_time_minimum', 'source': 'max(60, duration_minutes) * 1000',
     'context': {'calculated_at': CONTEXT['started_at']}, 'amount': 60000},
    {'name': 'subsecond', 'source': 'duration_minutes * 60',
     'context': {'calculated_at': '2026-09-21T17:30:00.500000+05:00'}, 'amount': 1},
    {'name': 'legacy_hourly', 'source': 'round_money(hourly_rate * max(60, floor(duration_minutes / 5) * 5) / 60, 1000, "half_down")',
     'parameters': {'hourly_rate': '100000'}, 'context': {'calculated_at': '2026-09-21T19:04:59+05:00'}, 'amount': 150000},
    {'name': 'lazy_if', 'source': 'if(subtotal > 0, 100, 1 / 0)', 'amount': 100},
    {'name': 'lazy_boolean', 'source': 'if(false && 1 / 0 > 0 || guest_count == 2, 100, 0)', 'amount': 100},
    {'name': 'division_zero', 'source': '1 / 0', 'error': True},
    {'name': 'negative_fee', 'source': '-1', 'error': True},
    {'name': 'overflow', 'source': '2147483648', 'error': True},
    {'name': 'invalid_step', 'source': 'round(100, 0)', 'error': True},
    {'name': 'invalid_window', 'source': 'minutes_in("09:00", "09:00")', 'error': True},
    {'name': 'invalid_clock', 'source': 'minutes_in("24:00", "09:00")', 'error': True},
    {'name': 'invalid_mode', 'source': 'round(100, 1, "bankers")', 'error': True},
    {'name': 'backwards', 'source': 'duration_minutes',
     'context': {'calculated_at': '2026-09-21T17:00:00+05:00'}, 'error': True},
    {'name': 'spring_dst', 'source': 'minutes_in("00:00", "09:00")', 'timezone': 'America/New_York',
     'context': {'started_at': '2026-03-08T00:00:00-05:00', 'calculated_at': '2026-03-08T09:00:00-04:00'}, 'amount': 480},
    {'name': 'fall_dst', 'source': 'minutes_in("00:00", "09:00")', 'timezone': 'America/New_York',
     'context': {'started_at': '2026-11-01T00:00:00-04:00', 'calculated_at': '2026-11-01T09:00:00-05:00'}, 'amount': 600},
    {'name': 'nonexistent_boundary', 'source': 'minutes_in("02:30", "09:00")', 'timezone': 'America/New_York',
     'context': {'started_at': '2026-03-08T00:00:00-05:00', 'calculated_at': '2026-03-08T09:00:00-04:00'}, 'amount': 330},
    {'name': 'ambiguous_boundary', 'source': 'minutes_in("02:30", "09:00")', 'timezone': 'Europe/Berlin',
     'context': {'started_at': '2026-10-25T00:00:00+02:00', 'calculated_at': '2026-10-25T09:00:00+01:00'}, 'amount': 450},
]

# The first hour is charged once at arrival rate, even across a shift boundary.
# Subsequent time is split into daily windows, without repeating the minimum.
for name, start, end, amount in [
    ('evening_full_hour', '2026-09-21T17:30', '2026-09-21T18:30', 50000),
    ('evening_partial_hour', '2026-09-21T17:45', '2026-09-21T18:15', 50000),
    ('evening_exact_hour', '2026-09-21T17:45', '2026-09-21T18:45', 50000),
    ('evening_tail', '2026-09-21T17:45', '2026-09-21T19:15', 100000),
    ('day_boundary', '2026-09-21T09:00', '2026-09-21T09:15', 50000),
    ('night_boundary', '2026-09-21T18:00', '2026-09-21T18:15', 100000),
    ('morning_first_hour', '2026-09-21T08:30', '2026-09-21T09:30', 100000),
    ('morning_tail', '2026-09-21T08:30', '2026-09-21T10:00', 125000),
    ('midnight', '2026-09-21T23:30', '2026-09-22T01:00', 150000),
    ('two_shift_tail', '2026-09-21T17:45', '2026-09-22T09:15', 1487500),
    ('zero_time', '2026-09-21T17:45', '2026-09-21T17:45', 50000),
    ('two_days', '2026-09-21T09:00', '2026-09-23T09:00', 3900000),
    ('fractional_minute', '2026-09-21T17:45', '2026-09-21T18:45:30', 50833),
]:
    start = start + ':00' if len(start) == 16 else start
    end = end + ':00' if len(end) == 16 else end
    CASES.append({'name': 'first_hour_schedule_' + name, 'source': FIRST_HOUR_SOURCE,
                  'parameters': {'day_rate': '50000', 'night_rate': '100000'},
                  'context': {'started_at': start + '+05:00', 'calculated_at': end + '+05:00'},
                  'amount': amount})

CASES.extend([
    {'name': 'offset_negative', 'source': 'minutes_in(add_minutes(started_at, -30), calculated_at, "09:00", "18:00")', 'amount': 60},
    {'name': 'offset_fraction_rejected', 'source': 'if(add_minutes(started_at, 0.5) > started_at, 1, 0)', 'error': True},
    {'name': 'offset_limit_rejected', 'source': 'if(add_minutes(started_at, 527041) > started_at, 1, 0)', 'error': True},
    {'name': 'offset_negative_limit_rejected', 'source': 'if(add_minutes(started_at, -527041) < started_at, 1, 0)', 'error': True},
    {'name': 'offset_lower_year_rejected', 'source': 'if(add_minutes(started_at, -1) < started_at, 1, 0)',
     'context': {'started_at': '1970-01-01T00:00:00Z', 'calculated_at': '1970-01-01T01:00:00Z'}, 'error': True},
    {'name': 'offset_upper_year_rejected', 'source': 'if(add_minutes(started_at, 60) > started_at, 1, 0)',
     'context': {'started_at': '9998-12-31T23:30:00Z', 'calculated_at': '9998-12-31T23:30:00Z'}, 'error': True},
    {'name': 'offset_dst_elapsed', 'source': 'if(time_in(add_minutes(started_at, 60), "03:00", "04:00"), 1, 0)',
     'timezone': 'America/New_York', 'context': {'started_at': '2026-03-08T01:30:00-05:00',
                                              'calculated_at': '2026-03-08T03:30:00-04:00'}, 'amount': 1},
])
