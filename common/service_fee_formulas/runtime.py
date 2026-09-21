"""Exact arithmetic and time-window semantics for formula language version 1."""

import math
import re
from datetime import datetime, time, timedelta, timezone
from fractions import Fraction
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .language import FormulaError, bounded, compile_formula, normalize_parameters


MAX_AMOUNT = 2_147_483_647
MAX_DURATION_DAYS = 366
ROUNDING_MODES = {'half_up', 'half_down', 'floor', 'ceil'}


def number(value):
    if isinstance(value, bool):
        raise FormulaError('Expected a number, received boolean.')
    try:
        return bounded(Fraction(str(value)))
    except (ValueError, ZeroDivisionError, TypeError):
        raise FormulaError('Invalid decimal number.') from None


def instant(value):
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00')) if isinstance(value, str) else value
        if not isinstance(result, datetime) or result.tzinfo is None or result.utcoffset() is None:
            raise ValueError()
        result = result.astimezone(timezone.utc)
        if not 1970 <= result.year <= 9998:
            raise ValueError()
        return result
    except (TypeError, ValueError, OverflowError):
        raise FormulaError('A timestamp with an explicit UTC offset is required.') from None


def clock(value):
    if not isinstance(value, str) or not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', value):
        raise FormulaError('Time windows require HH:MM between 00:00 and 23:59.')
    return time.fromisoformat(value)


def elapsed_minutes(start, end):
    delta = end - start
    if delta < timedelta(0) or delta > timedelta(days=MAX_DURATION_DAYS):
        raise FormulaError(f'Session duration must be between 0 and {MAX_DURATION_DAYS} days.')
    return Fraction((delta.days * 86400 + delta.seconds) * 1_000_000 + delta.microseconds, 60_000_000)


def minutes_in(start, end, lower, upper, zone):
    elapsed_minutes(start, end)
    lower, upper = clock(lower), clock(upper)
    if lower == upper:
        raise FormulaError('Window start and end must differ; use duration_minutes for a full day.')
    day = start.astimezone(zone).date() - timedelta(days=1)
    last_day = end.astimezone(zone).date()
    total = Fraction(0)
    while day <= last_day:
        finish_day = day + timedelta(days=1) if upper < lower else day
        left = datetime.combine(day, lower, zone).astimezone(timezone.utc)
        right = datetime.combine(finish_day, upper, zone).astimezone(timezone.utc)
        overlap_start, overlap_end = max(start, left), min(end, right)
        if overlap_end > overlap_start:
            total += elapsed_minutes(overlap_start, overlap_end)
        day += timedelta(days=1)
    return total


def round_number(value, step=Fraction(1), mode='half_up'):
    if step <= 0:
        raise FormulaError('Rounding step must be positive.')
    if mode not in ROUNDING_MODES:
        raise FormulaError('Rounding mode must be half_up, half_down, floor or ceil.')
    units = value / step
    if mode == 'floor':
        return bounded(Fraction(math.floor(units)) * step)
    if mode == 'ceil':
        return bounded(Fraction(math.ceil(units)) * step)
    magnitude = abs(units)
    integer = magnitude.numerator // magnitude.denominator
    remainder = magnitude - integer
    if remainder > Fraction(1, 2) or (remainder == Fraction(1, 2) and mode == 'half_up'):
        integer += 1
    return bounded(Fraction(integer if value >= 0 else -integer) * step)


class Evaluator:
    def __init__(self, parameters, *, subtotal, started_at, calculated_at, guest_count=1, timezone_name='Asia/Tashkent'):
        try:
            self.zone = ZoneInfo(timezone_name)
        except (ZoneInfoNotFoundError, ValueError, TypeError):
            raise FormulaError('Unknown restaurant time zone.') from None
        self.start, self.end = instant(started_at), instant(calculated_at)
        self.values = {name: number(value) for name, value in normalize_parameters(parameters).items()}
        subtotal, guest_count = number(subtotal), number(guest_count)
        if subtotal < 0 or guest_count < 0 or guest_count.denominator != 1:
            raise FormulaError('Subtotal and integer guest count must be nonnegative.')
        self.values.update(subtotal=subtotal, guest_count=guest_count,
                           duration_minutes=elapsed_minutes(self.start, self.end))
        self.values.update({'session.started_at': self.start, 'started_at': self.start,
                            'calculation.at': self.end, 'calculated_at': self.end})
        self.operations = 0

    def evaluate(self, node, depth=0):
        self.operations += 1
        if self.operations > 1000 or depth > 32:
            raise FormulaError('Formula evaluation limit exceeded.')
        kind, value, *args = node
        child = lambda n: self.evaluate(n, depth + 1)
        if kind == 'number':
            return number(value)
        if kind in ('string', 'boolean'):
            return value
        if kind == 'variable':
            return self.values[value]
        if kind == 'unary':
            operand = child(args[0])
            return not operand if value == '!' else -operand if value == '-' else operand
        if kind == 'binary':
            left = child(args[0])
            if value == '&&':
                return left and child(args[1])
            if value == '||':
                return left or child(args[1])
            right = child(args[1])
            if value in ('/', '%') and right == 0:
                raise FormulaError('Division by zero.')
            if value in ('==', '!=', '<', '<=', '>', '>='):
                return {'==': lambda: left == right, '!=': lambda: left != right,
                        '<': lambda: left < right, '<=': lambda: left <= right,
                        '>': lambda: left > right, '>=': lambda: left >= right}[value]()
            result = {'+': lambda: left + right, '-': lambda: left - right,
                      '*': lambda: left * right, '/': lambda: left / right,
                      '%': lambda: left - math.trunc(left / right) * right}[value]()
            return bounded(result)
        if kind == 'call':
            if value == 'if':
                return child(args[1] if child(args[0]) else args[2])
            values = [child(arg) for arg in args]
            if value in ('min', 'max'):
                return min(values) if value == 'min' else max(values)
            if value == 'abs':
                return abs(values[0])
            if value in ('floor', 'ceil'):
                return round_number(values[0], values[1] if len(values) > 1 else Fraction(1), value)
            if value in ('round', 'round_money'):
                return round_number(*values)
            if value == 'minutes_in':
                if len(values) == 2:
                    values = [self.start, self.end, *values]
                return minutes_in(*values, self.zone)
            if value == 'add_minutes':
                timestamp, offset = values
                if offset.denominator != 1 or abs(offset) > MAX_DURATION_DAYS * 1440:
                    raise FormulaError('Minute offset must be an integer within 366 days.')
                try:
                    return instant(timestamp + timedelta(minutes=int(offset)))
                except OverflowError:
                    raise FormulaError('Timestamp after minute offset is out of range.') from None
            if value == 'time_in':
                timestamp, lower, upper = values
                lower, upper = clock(lower), clock(upper)
                if lower == upper:
                    raise FormulaError('Window start and end must differ.')
                local_time = timestamp.astimezone(self.zone).time()
                return lower <= local_time < upper if lower < upper else local_time >= lower or local_time < upper
        raise FormulaError('Unsupported formula operation.')


def evaluate_formula(source, parameters=None, **context):
    """Compile trusted source each time; client-supplied AST is never authoritative."""
    program = compile_formula(source, parameters)
    evaluator = Evaluator(parameters, **context)
    trace = []
    for binding in program['bindings']:
        value = evaluator.evaluate(binding['value'])
        evaluator.values[binding['name']] = value
        trace.append({'name': binding['name'], 'value': str(value)})
    result = evaluator.evaluate(program['result'])
    if not isinstance(result, Fraction) or result < 0 or result > MAX_AMOUNT:
        raise FormulaError(f'Fee must be between 0 and {MAX_AMOUNT}.')
    return {'amount': int(round_number(result)), 'exact': str(result), 'bindings': trace,
            'duration_minutes': str(evaluator.values['duration_minutes']),
            'time_dependent': program['time_dependent'], 'version': program['version']}
