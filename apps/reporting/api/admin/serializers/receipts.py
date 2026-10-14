from urllib.parse import urlsplit


def _find_qr_url(payload, depth=0):
    if not isinstance(payload, dict) or depth > 4:
        return None
    for key in ('qrCodeUrl', 'qr_code_url', 'QRCodeURL'):
        value = payload.get(key)
        if not isinstance(value, str):
            continue
        value = value.strip()
        try:
            parsed = urlsplit(value)
        except ValueError:
            continue
        if parsed.scheme.lower() in ('http', 'https') and parsed.netloc:
            return value
    for value in payload.values():
        url = _find_qr_url(value, depth + 1)
        if url:
            return url
    return None


def serialize_receipt_report_row(row):
    result = dict(row)
    payload = result.pop('payload', None)
    result['qr_code_url'] = _find_qr_url(payload) if result['kind'] == 'fiscal' else None
    return result
