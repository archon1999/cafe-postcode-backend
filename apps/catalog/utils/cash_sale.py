from decimal import Decimal


def _find_first(payload, keys: set[str]):
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key in keys:
                return value
            nested = _find_first(value, keys)
            if nested not in (None, ''):
                return nested
    if isinstance(payload, list):
        for item in payload:
            nested = _find_first(item, keys)
            if nested not in (None, ''):
                return nested
    return None


def is_cash_sale_forbidden_payload(*payloads) -> bool:
    value = _find_first(list(payloads), {'cashSale', 'cash_sale'})
    if value in (None, ''):
        return False
    try:
        return Decimal(str(value)) == 0
    except Exception:
        return False


def is_catalog_category_cash_sale_forbidden(category) -> bool:
    return is_cash_sale_forbidden_payload(getattr(category, 'mxik_payload', None))


def is_catalog_item_cash_sale_forbidden(item) -> bool:
    catalog_item = getattr(item, 'catalog_item', item)
    return is_cash_sale_forbidden_payload(
        getattr(catalog_item, 'mxik_payload', None),
        getattr(getattr(catalog_item, 'category', None), 'mxik_payload', None),
    )
