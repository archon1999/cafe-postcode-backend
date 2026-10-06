from .fiscal_classification import fiscal_package_code, fiscal_units


BARCODE_KEYS = {'barcode', 'Barcode', 'bar_code', 'barCode', 'international_code', 'internationalCode', 'gtin', 'GTIN'}


def _first_barcode(value):
    # Preserve the provider's depth-first traversal and leading zeroes.
    if isinstance(value, dict):
        for key, nested in value.items():
            if key in BARCODE_KEYS:
                return nested
            found = _first_barcode(nested)
            if found not in (None, ''):
                return found
    elif isinstance(value, list):
        for nested in value:
            found = _first_barcode(nested)
            if found not in (None, ''):
                return found
    return None


def pos_fiscal_payload(item_payload, category_payload):
    """Project saved classification without copying Tasnif's package directory.

    Raw lookup data stays in the catalog. These fields are the complete input
    used by offline receipt construction; marking and cash restrictions are
    separate, resolved fields on the menu item.
    """
    payload = {}
    if package_code := fiscal_package_code(item_payload, category_payload):
        # Pre-2.4.1 Agents mistake packageCode for Units, but ignore this key.
        payload['primaryPackage'] = {'code': package_code}
    units = fiscal_units(item_payload, category_payload)
    if units is not None:
        payload['unitCode'] = units
    for source in (item_payload, category_payload):
        barcode = ''.join(char for char in str(_first_barcode(source) or '') if char.isdigit())[:64]
        if barcode:
            payload['barcode'] = barcode
            break
    return payload
