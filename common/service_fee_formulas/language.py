"""Bounded service-fee DSL compiler. Never executes Python or JavaScript."""

import json
import re
from fractions import Fraction


VERSION = 1
MAX_SOURCE = 8000
MAX_NODES = 400
MAX_DEPTH = 32
MAX_VALUE = 10**15
SYSTEM_TYPES = {
    'subtotal': 'number', 'duration_minutes': 'number', 'guest_count': 'number',
    'session.started_at': 'time', 'calculation.at': 'time',
    'started_at': 'time', 'calculated_at': 'time',
}
FUNCTIONS = {'if', 'min', 'max', 'abs', 'floor', 'ceil', 'round', 'round_money', 'minutes_in', 'time_in', 'add_minutes'}
RESERVED = set(SYSTEM_TYPES) | FUNCTIONS | {'let', 'return', 'true', 'false'}
TOKEN = re.compile(
    r'(?P<space>\s+|//[^\n]*)|(?P<number>\d+(?:\.\d+)?)|'
    r'(?P<string>"(?:[^"\\\r\n]|\\["\\])*")|'
    r'(?P<name>[A-Za-z_][A-Za-z_0-9]*(?:\.[A-Za-z_][A-Za-z_0-9]*)*)|'
    r'(?P<op>==|!=|<=|>=|&&|\|\||[+*/%<>()!,;=\-])'
)
PRECEDENCE = {'||': 1, '&&': 2, '==': 3, '!=': 3, '<': 4, '<=': 4,
              '>': 4, '>=': 4, '+': 5, '-': 5, '*': 6, '/': 6, '%': 6}


class FormulaError(ValueError):
    def __init__(self, message, position=None):
        self.message = message
        self.position = position
        super().__init__(f'{message} (position {position + 1})' if position is not None else message)

    def as_dict(self):
        return {'message': self.message, 'position': self.position}


def bounded(value):
    if abs(value) > MAX_VALUE or value.numerator.bit_length() > 256 or value.denominator.bit_length() > 256:
        raise FormulaError('Numeric precision or magnitude limit exceeded.')
    return value


def normalize_parameters(parameters):
    if parameters is None:
        parameters = {}
    if not isinstance(parameters, dict) or len(parameters) > 32:
        raise FormulaError('Parameters must be an object with at most 32 entries.')
    result = {}
    for name, raw in parameters.items():
        if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]{0,63}', name) or name in RESERVED:
            raise FormulaError(f'Invalid or reserved parameter name: {name}.')
        if isinstance(raw, bool) or not isinstance(raw, (str, int, float)):
            raise FormulaError(f'Parameter {name} must be a decimal number.')
        text = str(raw)
        if len(text) > 40 or not re.fullmatch(r'-?\d+(?:\.\d+)?', text):
            raise FormulaError(f'Parameter {name} must be a decimal number without an exponent.')
        bounded(Fraction(text))
        result[name] = text
    return result


class Parser:
    def __init__(self, source, parameters):
        if not isinstance(source, str) or not source.strip() or len(source) > MAX_SOURCE:
            raise FormulaError(f'Formula must contain 1 to {MAX_SOURCE} characters.')
        self.tokens = []
        position = 0
        while position < len(source):
            match = TOKEN.match(source, position)
            if not match:
                raise FormulaError('Unexpected character.', position)
            if match.lastgroup != 'space':
                self.tokens.append((match.lastgroup, match.group(), position))
            position = match.end()
        if len(self.tokens) > 2000:
            raise FormulaError('Formula has too many tokens.')
        self.tokens.append(('end', '', len(source)))
        self.index = 0
        self.nodes = 0
        self.types = {**SYSTEM_TYPES, **{name: 'number' for name in parameters}}
        self.time_dependent = False

    @property
    def token(self):
        return self.tokens[self.index]

    def take(self, expected=None):
        token = self.token
        if expected is not None and token[1] != expected:
            raise FormulaError(f'Expected {expected!r}.', token[2])
        self.index += 1
        return token

    def node(self, *values):
        self.nodes += 1
        if self.nodes > MAX_NODES:
            raise FormulaError('Formula has too many operations.', self.token[2])
        return list(values)

    def expression(self, minimum=0, depth=0):
        if depth > MAX_DEPTH:
            raise FormulaError('Formula is nested too deeply.', self.token[2])
        kind, text, position = self.take()
        if text in ('-', '+', '!'):
            child, child_type = self.expression(7, depth + 1)
            expected = 'boolean' if text == '!' else 'number'
            self.require(child_type == expected, f'{text} requires {expected}.', position)
            left, value_type = self.node('unary', text, child), expected
        elif text == '(':
            left, value_type = self.expression(depth=depth + 1)
            self.take(')')
        elif kind == 'number':
            self.require(len(text) <= 40, 'Number is too long.', position)
            bounded(Fraction(text))
            left, value_type = self.node('number', text), 'number'
        elif kind == 'string':
            left, value_type = self.node('string', json.loads(text)), 'string'
        elif text in ('true', 'false'):
            left, value_type = self.node('boolean', text == 'true'), 'boolean'
        elif kind == 'name' and self.token[1] == '(':
            self.take('(')
            args, types = [], []
            if self.token[1] != ')':
                while True:
                    arg, arg_type = self.expression(depth=depth + 1)
                    args.append(arg)
                    types.append(arg_type)
                    if self.token[1] != ',':
                        break
                    self.take(',')
            self.take(')')
            value_type = self.function_type(text, types, position)
            left = self.node('call', text, *args)
        elif kind == 'name':
            self.require(text in self.types, f'Unknown variable: {text}.', position)
            value_type = self.types[text]
            self.time_dependent |= text in {'duration_minutes', 'calculation.at', 'calculated_at'}
            left = self.node('variable', text)
        else:
            raise FormulaError('Expected an expression.', position)
        while self.token[1] in PRECEDENCE and PRECEDENCE[self.token[1]] >= minimum:
            _, operator, position = self.take()
            right, right_type = self.expression(PRECEDENCE[operator] + 1, depth + 1)
            if operator in ('&&', '||'):
                self.require(value_type == right_type == 'boolean', 'Boolean operands required.', position)
                result_type = 'boolean'
            elif operator in ('==', '!=', '<', '<=', '>', '>='):
                self.require(value_type == right_type and (operator in ('==', '!=') or value_type in ('number', 'time')),
                             'Comparison operands must have matching types.', position)
                result_type = 'boolean'
            else:
                self.require(value_type == right_type == 'number', 'Numeric operands required.', position)
                result_type = 'number'
            left, value_type = self.node('binary', operator, left, right), result_type
        return left, value_type

    @staticmethod
    def require(condition, message, position):
        if not condition:
            raise FormulaError(message, position)

    def function_type(self, name, types, position):
        valid, result = False, 'number'
        if name == 'if':
            valid = len(types) == 3 and types[0] == 'boolean' and types[1] == types[2]
            result = types[1] if len(types) > 1 else 'number'
        elif name in ('min', 'max'):
            valid = 2 <= len(types) <= 16 and all(t == 'number' for t in types)
        elif name == 'abs':
            valid = types == ['number']
        elif name in ('floor', 'ceil'):
            valid = types in (['number'], ['number', 'number'])
        elif name in ('round', 'round_money'):
            valid = types in (['number'], ['number', 'number'], ['number', 'number', 'string'])
        elif name == 'minutes_in':
            valid = types in (['string', 'string'], ['time', 'time', 'string', 'string'])
            self.time_dependent = True
        elif name == 'add_minutes':
            valid = types == ['time', 'number']
            result = 'time'
        elif name == 'time_in':
            valid = types == ['time', 'string', 'string']
            result = 'boolean'
        self.require(valid, f'Unknown function or invalid arguments: {name}.', position)
        return result

    def parse(self):
        bindings = []
        while self.token[1] == 'let':
            self.take('let')
            kind, name, position = self.take()
            self.require(kind == 'name' and len(name) <= 64 and '.' not in name and name not in self.types and name not in RESERVED,
                         'Binding name must be new and must not be reserved.', position)
            self.take('=')
            expression, value_type = self.expression()
            self.take(';')
            self.types[name] = value_type
            bindings.append({'name': name, 'value': expression})
            self.require(len(bindings) <= 32, 'At most 32 bindings are allowed.', position)
        if self.token[1] == 'return':
            self.take('return')
        result, value_type = self.expression()
        self.require(value_type == 'number', 'Formula must return a monetary number.', self.token[2])
        if self.token[1] == ';':
            self.take(';')
        self.require(self.token[0] == 'end', 'Unexpected text after result.', self.token[2])
        # A long left-associative chain also needs a runtime depth bound.
        def depth(node):
            return 1 + max((depth(child) for child in node if isinstance(child, list)), default=0)
        if max(depth(result), *(depth(b['value']) for b in bindings), 0) > MAX_DEPTH:
            raise FormulaError('Formula operation tree is too deep.')
        return {'version': VERSION, 'bindings': bindings, 'result': result,
                'time_dependent': self.time_dependent}


def compile_formula(source, parameters=None):
    return Parser(source, normalize_parameters(parameters)).parse()
