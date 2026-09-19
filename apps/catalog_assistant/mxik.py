import re
import httpx
from django.core.cache import cache
from rest_framework.exceptions import ValidationError


def search_mxik(query):
    query = query.strip()[:100]
    if len(query) < 2:
        return []
    cache_key = 'management-mxik:v2:' + query.casefold()
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    numeric = query.isdigit()
    # Tasnif's main search uses `text`; search-symbol is typo suggestions and
    # can return unrelated products (e.g. tea -> musical instrument).
    endpoint = 'mxik/search/by-params'
    params = {'mxikCode' if numeric else 'text': query, 'size': 20, 'lang': 'uz'}
    try:
        response = httpx.get(f'https://tasnif.soliq.uz/api/cls-api/{endpoint}', params=params, timeout=8)
        response.raise_for_status()
        data = response.json()
        if isinstance(data, dict):
            data = data.get('data', data)
        if isinstance(data, dict):
            data = data.get('content', [data])
        rows = []
        for item in data[:20]:
            code = str(item.get('mxikCode') or item.get('mxik') or item.get('code') or '')
            name = str(item.get('mxikName') or item.get('name') or item.get('shortName') or item.get('subPositionName') or '')
            if re.fullmatch(r'\d{17}', code):
                rows.append({'code': code, 'name': name[:300]})
        rows = list({row['code']: row for row in rows}.values())
        cache.set(cache_key, rows, 3600)
        return rows
    except (httpx.HTTPError, ValueError, TypeError, AttributeError):
        raise ValidationError('MXIK qidiruvi vaqtincha ishlamayapti. Birozdan keyin qayta urinib ko‘ring.') from None
