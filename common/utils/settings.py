from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def get_setting(settings: Mapping[str, Any] | None, *keys: str, default=None, allow_blank: bool = False):
    """Return the first configured value across supported key aliases."""
    values = settings or {}
    for key in keys:
        value = values.get(key)
        if value is None or (not allow_blank and value == ''):
            continue
        return value
    return default


def coerce_bool(value, *, default: bool = False) -> bool:
    """Coerce common JSON/config boolean forms without treating arbitrary text as true."""
    if value is None or value == '':
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized in {'1', 'true', 'yes', 'on'}:
            return True
        if normalized in {'0', 'false', 'no', 'off'}:
            return False
    return default


def coerce_int(value, *, default: int = 0, minimum: int | None = None, maximum: int | None = None) -> int:
    """Coerce a config value to int and optionally clamp it to a safe range."""
    if isinstance(value, bool):
        result = default
    else:
        try:
            result = int(value)
        except (TypeError, ValueError, OverflowError):
            result = default
    if minimum is not None:
        result = max(result, minimum)
    if maximum is not None:
        result = min(result, maximum)
    return result
