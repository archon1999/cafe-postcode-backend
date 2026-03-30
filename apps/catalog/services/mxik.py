import os
from typing import Any

import httpx


class MxikError(Exception):
    pass


class MxikClient:
    def __init__(self):
        self.base_url = os.getenv('MXIK_API_BASE_URL', 'https://tasnif.soliq.uz/api/cls-api')
        self.timeout = float(os.getenv('MXIK_TIMEOUT', '10'))

    @staticmethod
    def _normalize_lang(lang: str | None) -> str:
        return 'ru' if lang == 'ru' else 'uz'

    @staticmethod
    def _normalize_item(payload: dict[str, Any]) -> dict[str, Any]:
        code = str(payload.get('mxikCode') or payload.get('code') or '').strip()
        name = str(payload.get('mxikName') or payload.get('name') or payload.get('shortName') or '').strip()
        if not name:
            name = ' / '.join(
                filter(
                    None,
                    [
                        payload.get('subPositionName'),
                        payload.get('positionName'),
                        payload.get('className'),
                    ],
                )
            ).strip()
        label = ' - '.join(filter(None, [code, name])) or code or name
        return {
            'code': code,
            'name': name,
            'label': label,
            'raw': payload,
        }

    @staticmethod
    def _extract_items(payload: dict[str, Any] | list[Any]) -> list[dict[str, Any]]:
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        if not isinstance(payload, dict):
            return []
        data = payload.get('data')
        if isinstance(data, dict):
            content = data.get('content')
            if isinstance(content, list):
                return [item for item in content if isinstance(item, dict)]
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        return [payload]

    def _request(self, path: str, params: dict[str, Any]) -> dict[str, Any] | list[Any]:
        try:
            response = httpx.get(
                f'{self.base_url.rstrip("/")}/{path.lstrip("/")}',
                params=params,
                timeout=self.timeout,
                follow_redirects=True,
            )
            response.raise_for_status()
        except httpx.HTTPError as error:
            raise MxikError(str(error)) from error
        return response.json()

    def search(self, query: str, *, lang: str = 'uz', limit: int = 20) -> list[dict[str, Any]]:
        if not query.strip():
            raise MxikError('MXIK search query cannot be empty.')
        payload = self._request(
            'mxik/search-symbol',
            {
                'search_text': query.strip(),
                'size': limit,
                'lang': self._normalize_lang(lang),
            },
        )
        return [self._normalize_item(item) for item in self._extract_items(payload)]

    def search_by_code(self, code: str, *, lang: str = 'uz', limit: int = 20) -> list[dict[str, Any]]:
        if not code.strip():
            raise MxikError('MXIK code query cannot be empty.')
        payload = self._request(
            'mxik/search/by-params',
            {
                'mxikCode': code.strip(),
                'size': limit,
                'lang': self._normalize_lang(lang),
            },
        )
        return [self._normalize_item(item) for item in self._extract_items(payload)]

    def lookup(self, code: str, *, lang: str = 'uz') -> dict[str, Any]:
        if not code.strip():
            raise MxikError('MXIK code cannot be empty.')
        payload = self._request(
            'mxik/get/by-mxik',
            {
                'mxikCode': code.strip(),
                'lang': self._normalize_lang(lang),
            },
        )
        items = self._extract_items(payload)
        if not items:
            raise MxikError('MXIK code not found.')
        return self._normalize_item(items[0])
