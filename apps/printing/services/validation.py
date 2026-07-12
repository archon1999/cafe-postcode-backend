import re
from collections.abc import Iterable

from apps.printing.presets import VARIABLES_BY_KIND


VARIABLE_PATTERN = re.compile(r'{{\s*([a-zA-Z][a-zA-Z0-9_.]*)\s*}}')
ALLOWED_BLOCK_TYPES = frozenset({'text', 'two_column_row', 'divider', 'spacer', 'items_table', 'totals', 'metadata', 'qr', 'logo', 'feed', 'cut'})
REQUIRED_ROLES_BY_KIND = {
    'kitchen_ticket': frozenset({'restaurant_header', 'order_header', 'items'}),
    'payment_receipt_plain': frozenset({'restaurant_header', 'order_header', 'items', 'totals', 'payment'}),
    'payment_receipt_fiscal': frozenset(
        {'restaurant_header', 'order_header', 'items', 'totals', 'payment', 'fiscal', 'fiscal_qr'}
    ),
}


class TemplateLayoutValidationError(ValueError):
    def __init__(self, errors: dict[str, list[str]]):
        super().__init__('Print template layout is invalid.')
        self.errors = errors


def _iter_strings(value) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for child in value.values():
            yield from _iter_strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from _iter_strings(child)


def validate_template_layout(*, kind: str, layout: dict) -> dict:
    errors: dict[str, list[str]] = {}

    if not isinstance(layout, dict):
        raise TemplateLayoutValidationError({'layout': ['Layout must be an object.']})

    if layout.get('schemaVersion') != 1:
        errors.setdefault('schemaVersion', []).append('Only schema version 1 is supported.')

    paper_width = layout.get('paperWidthMm')
    if paper_width != 80:
        errors.setdefault('paperWidthMm', []).append('Only 80 mm paper is supported.')

    blocks = layout.get('blocks')
    if not isinstance(blocks, list) or not blocks:
        errors.setdefault('blocks', []).append('At least one block is required.')
        blocks = []
    elif len(blocks) > 40:
        errors.setdefault('blocks', []).append('A template may contain at most 40 blocks.')

    block_ids: set[str] = set()
    roles: set[str] = set()
    for index, block in enumerate(blocks):
        path = f'blocks.{index}'
        if not isinstance(block, dict):
            errors.setdefault(path, []).append('Block must be an object.')
            continue
        block_type = block.get('type')
        if block_type not in ALLOWED_BLOCK_TYPES:
            errors.setdefault(f'{path}.type', []).append(f'Unsupported block type: {block_type!r}.')
        block_id = str(block.get('id') or '').strip()
        if block_id:
            if block_id in block_ids:
                errors.setdefault(f'{path}.id', []).append('Block id must be unique.')
            block_ids.add(block_id)
        role = str(block.get('role') or '').strip()
        if role:
            roles.add(role)

    required_roles = REQUIRED_ROLES_BY_KIND.get(kind)
    if required_roles is None:
        errors.setdefault('kind', []).append('Unsupported print template kind.')
    else:
        missing_roles = sorted(required_roles - roles)
        if missing_roles:
            errors.setdefault('blocks', []).append(f'Missing required roles: {", ".join(missing_roles)}.')

    allowed_variables = set(VARIABLES_BY_KIND.get(kind, ()))
    used_variables = {
        match.group(1)
        for value in _iter_strings(blocks)
        for match in VARIABLE_PATTERN.finditer(value)
    }
    unknown_variables = sorted(used_variables - allowed_variables)
    if unknown_variables:
        errors.setdefault('variables', []).append(f'Unknown variables: {", ".join(unknown_variables)}.')

    serialized_size = len(str(layout).encode('utf-8'))
    if serialized_size > 64 * 1024:
        errors.setdefault('layout', []).append('Layout exceeds the 64 KiB limit.')

    if errors:
        raise TemplateLayoutValidationError(errors)
    return layout
