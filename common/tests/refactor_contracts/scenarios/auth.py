from __future__ import annotations

from datetime import datetime
from typing import cast

from .. import normalize_scenario_expected, validate_scenario_v1


def auth_scenario(
    scenario_id: str,
    expected: dict[str, object],
    *,
    volatile_paths: list[dict[str, str]] | None = None,
) -> dict[str, object]:
    scenario = {
        "schemaVersion": 1,
        "scenarioId": scenario_id,
        "capability": "CAP-AUTH",
        "mode": "remote",
        "actor": {
            "kind": "anonymous",
            "role": "anonymous_device_terminal",
            "restaurantRef": "restaurant:primary",
        },
        "input": {},
        "expected": expected,
        "volatilePaths": volatile_paths or [],
        "unorderedCollections": [],
    }
    validate_scenario_v1(scenario)
    return normalize_scenario_expected(scenario)


def canonical_error(status_code: int, data: object) -> dict[str, object]:
    return {"httpStatus": status_code, "body": _plain(data)}


def canonical_restaurant(
    status_code: int,
    data: dict[str, object],
    *,
    restaurant_refs: dict[str, str],
) -> dict[str, object]:
    return {
        "httpStatus": status_code,
        "restaurantRef": _fixture_ref(
            data["restaurant_id"], restaurant_refs, "restaurant"
        ),
        "restaurantName": data["restaurant_name"],
        "backgroundUrl": data["pos_auth_background_image_url"],
        "serviceFeeEnabled": data["service_fee_enabled"],
        "serviceFeePercent": data["service_fee_percent"],
        "vatEnabled": data["vat_enabled"],
        "vatPercent": data["vat_percent"],
        "markingCheckEnabled": data["marking_check_enabled"],
    }


def canonical_pin_session(
    status_code: int,
    data: dict[str, object],
    *,
    user_refs: dict[str, str],
    role_refs: dict[str, str],
    restaurant_refs: dict[str, str],
    tariff_refs: dict[str, str],
) -> dict[str, object]:
    user = cast(dict[str, object], data["user"])
    role = cast(dict[str, object], user["role"])
    session = cast(dict[str, object], data["session"])
    tariff = cast(dict[str, object], data["tariff"])
    restaurant = cast(dict[str, object], data["restaurant_context"])
    created_at = _instant(session["created_at"])
    expires_at = _instant(session["expires_at"])
    return {
        "httpStatus": status_code,
        "tokenPresent": bool(data["token"]),
        "user": {
            "userRef": _fixture_ref(user["id"], user_refs, "user"),
            "username": user["username"],
            "fullName": user["full_name"],
            "permissionCodes": user["permission_codes"],
            "roleRef": _fixture_ref(role["id"], role_refs, "role"),
            "roleName": role["name"],
        },
        "session": {
            "id": session["id"],
            "status": session["status"],
            "surface": session["surface"],
            "ttlSeconds": round((expires_at - created_at).total_seconds()),
            "clientIp": session["client_ip"],
            "userAgent": session["user_agent"],
            "revokedAt": session["revoked_at"],
            "lastSeenAtPresent": bool(session["last_seen_at"]),
        },
        "restaurantAccessActive": data["restaurant_access_active"],
        "roleCodes": data["role_codes"],
        "tariff": {
            "tariffRef": _fixture_ref(tariff["id"], tariff_refs, "tariff"),
            "name": tariff["name"],
            "permissionCodes": tariff["permission_codes"],
            "roleCodes": tariff["role_codes"],
        },
        "restaurant": canonical_restaurant(
            200, restaurant, restaurant_refs=restaurant_refs
        ),
    }


def _fixture_ref(value: object, refs: dict[str, str], kind: str) -> str:
    key = str(value)
    if key not in refs:
        raise AssertionError(f"Unexpected {kind} identity: {key}")
    return refs[key]


def _instant(value: object) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _plain(value: object) -> object:
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if isinstance(value, str):
        return str(value)
    return value
