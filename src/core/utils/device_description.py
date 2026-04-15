from typing import Optional


DEVICE_ID_DESCRIPTION_KEY = "device_id"
SAVED_ANON_TRAFFIC_FLAG_DESCRIPTION_KEY = "created_with_saved_anon_traffic"
SAVED_ANON_TRAFFIC_BYTES_DESCRIPTION_KEY = "saved_anon_traffic_bytes"


def build_device_id_description_line(device_id: str) -> str:
    return f"{DEVICE_ID_DESCRIPTION_KEY}: {device_id}"


def _split_description_line(line: str) -> tuple[str, bool, str]:
    key, separator, value = line.partition(":")
    return key.strip().lower(), bool(separator), value.strip()


def extract_device_id_from_description(description: Optional[str]) -> Optional[str]:
    if not description:
        return None

    for line in description.splitlines():
        key, has_separator, value = _split_description_line(line)
        if has_separator and key == DEVICE_ID_DESCRIPTION_KEY:
            return value or None

    return None


def description_has_device_id(description: Optional[str], device_id: str) -> bool:
    if not description:
        return False

    for line in description.splitlines():
        key, has_separator, value = _split_description_line(line)
        if has_separator and key == DEVICE_ID_DESCRIPTION_KEY and value == device_id:
            return True

    return False


def append_device_id_to_description(description: Optional[str], device_id: str) -> str:
    base = (description or "").strip()
    if not device_id:
        return base

    device_line = build_device_id_description_line(device_id)
    if description_has_device_id(base, device_id):
        return base

    return f"{base}\n{device_line}" if base else device_line


def append_saved_anon_traffic_to_description(
    description: Optional[str],
    traffic_bytes: int,
) -> str:
    base = (description or "").strip()
    if traffic_bytes <= 0:
        return base

    excluded_keys = {
        SAVED_ANON_TRAFFIC_FLAG_DESCRIPTION_KEY,
        SAVED_ANON_TRAFFIC_BYTES_DESCRIPTION_KEY,
    }
    lines = []

    for line in base.splitlines():
        key, has_separator, _ = _split_description_line(line)
        if has_separator and key in excluded_keys:
            continue
        lines.append(line)

    lines.extend(
        (
            f"{SAVED_ANON_TRAFFIC_FLAG_DESCRIPTION_KEY}: true",
            f"{SAVED_ANON_TRAFFIC_BYTES_DESCRIPTION_KEY}: {traffic_bytes}",
        )
    )

    return "\n".join(lines)
