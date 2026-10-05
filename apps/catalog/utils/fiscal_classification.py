UNIT_KEYS = ('unit_code', 'unitCode', 'common_unit_code', 'commonUnitCode', 'units', 'Units', 'unit', 'Unit')
PACKAGE_KEYS = ('package_code', 'packageCode', 'PackageCode', 'package_code_id', 'packageCodeId', 'package', 'Package')


def _values(payload, keys):
    if isinstance(payload, dict):
        for key in keys:
            if key in payload:
                yield payload[key]
        for key in sorted(payload):
            yield from _values(payload[key], keys)
    elif isinstance(payload, list):
        for value in payload:
            yield from _values(value, keys)


def fiscal_units(*payloads):
    for payload in payloads:
        for value in _values(payload, UNIT_KEYS):
            if isinstance(value, bool):
                continue
            try:
                code = int(value)
            except (TypeError, ValueError):
                continue
            if code > 0:
                return code
    return None


def _package_code(value):
    if isinstance(value, dict):
        value = value.get('code')
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return ''
    return str(value).strip()[:64]


def fiscal_package_code(*payloads):
    for payload in payloads:
        for value in _values(payload, PACKAGE_KEYS):
            if code := _package_code(value):
                return code
        if not isinstance(payload, dict):
            continue
        for key in ('primaryPackage', 'primary_package'):
            if code := _package_code(payload.get(key)):
                return code
        packages = payload.get('packages')
        if not isinstance(packages, list):
            continue
        packages = [package for package in packages if isinstance(package, dict) and _package_code(package)]
        # Match the primary package displayed by the catalog's Tasnif lookup.
        primary = next((package for package in packages if str(package.get('isUnitPackage')) == '1'), None)
        if primary is None:
            primary = next((package for package in packages if not package.get('parentCode')), None)
        if primary is None:
            primary = next(iter(packages), None)
        if code := _package_code(primary):
            return code
    return ''
