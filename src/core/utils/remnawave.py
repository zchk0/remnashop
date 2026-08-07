from typing import Any, Optional


def extract_expiration_hours(raw_payload: dict[str, Any]) -> Optional[int]:
    meta = raw_payload.get("meta")
    if not isinstance(meta, dict):
        return None

    expiration = meta.get("expiration")
    if isinstance(expiration, bool) or not isinstance(expiration, (int, float)):
        return None
    if isinstance(expiration, float) and not expiration.is_integer():
        return None

    return int(expiration)
