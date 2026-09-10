def fiscal_tax_identifier(value):
    """Map the single STIR/JSHSHIR field without changing taxpayer identity."""
    identifier = str(value or '').strip()
    if not identifier:
        return {}
    if not identifier.isascii() or not identifier.isdigit() or len(identifier) not in (9, 14):
        raise ValueError('STIR 9 ta yoki JSHSHIR 14 ta raqamdan iborat bo‘lishi kerak.')
    return {'PINFL' if len(identifier) == 14 else 'TIN': identifier}
