def payload_requires_marking(payload) -> bool:
    if not isinstance(payload, dict):
        return False
    value = payload.get('label')
    if value is None:
        value = payload.get('Label')
    return str(value).strip().lower() in {'1', 'true', 'yes'}


def payload_gtin(payload) -> str:
    if not isinstance(payload, dict):
        return ''
    for key in ('gtin', 'GTIN', 'barcode', 'Barcode', 'barCode', 'internationalCode', 'international_code'):
        value = payload.get(key)
        digits = ''.join(ch for ch in str(value or '') if ch.isdigit())
        if digits:
            return digits[:32]
    return ''


def item_requires_marking(item) -> bool:
    return bool(getattr(item, 'requires_marking', False) or payload_requires_marking(getattr(item, 'mxik_payload', None)))


def item_marking_gtin(item) -> str:
    explicit = ''.join(ch for ch in str(getattr(item, 'marking_gtin', '') or '') if ch.isdigit())
    if explicit:
        return explicit[:32]
    return payload_gtin(getattr(item, 'mxik_payload', None))
