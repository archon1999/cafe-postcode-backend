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


def _source_classification(source, cache):
    if cache is not None:
        cached = cache.get(id(source))
        if cached is not None and cached[0] is source:
            return cached[1]
    fields = (
        fiscal_package_code(source),
        fiscal_units(source),
        ''.join(char for char in str(_first_barcode(source) or '') if char.isdigit())[:64],
    )
    if cache is not None:
        # Keep the source alive until this serializer finishes, preventing id reuse.
        # This cache belongs to the serializer context, never a worker/global cache.
        cache[id(source)] = (source, fields)
    return fields


def pos_fiscal_payload(item_payload, category_payload, *, cache=None):
    """Project saved classification without copying Tasnif's package directory.

    Raw lookup data stays in the catalog. These fields are the complete input
    used by offline receipt construction; marking and cash restrictions are
    separate, resolved fields on the menu item.
    """
    item = _source_classification(item_payload, cache)
    category = (
        _source_classification(category_payload, cache)
        if not item[0] or item[1] is None or not item[2]
        else ('', None, '')
    )
    payload = {}
    if package_code := item[0] or category[0]:
        # Pre-2.4.1 Agents mistake packageCode for Units, but ignore this key.
        payload['primaryPackage'] = {'code': package_code}
    units = item[1] if item[1] is not None else category[1]
    if units is not None:
        payload['unitCode'] = units
    if barcode := item[2] or category[2]:
        payload['barcode'] = barcode
    return payload
