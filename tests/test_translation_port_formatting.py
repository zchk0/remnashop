from pathlib import Path

import pytest
from fluent_compiler.bundle import FluentBundle
from fluentogram.translator import FluentTranslator


@pytest.fixture(scope="module")
def translator() -> FluentTranslator:
    translation_dir = Path("assets/translations/ru")
    texts = [path.read_text("utf-8") for path in sorted(translation_dir.glob("*.ftl"))]
    bundle = FluentBundle.from_string(
        locale="ru",
        text="\n".join(texts),
        use_isolating=False,
    )
    return FluentTranslator(locale="ru", translator=bundle)


@pytest.mark.parametrize(
    ("key", "kwargs"),
    [
        (
            "event-node.connection-restored",
            {
                "country": "RU",
                "name": "node",
                "address": "51.250.42.16",
                "port": 2222,
                "traffic_used": "1 GB",
                "traffic_limit": "unlimited",
                "last_status_message": 0,
                "last_status_change": "02.09.26 03:45:42",
            },
        ),
        (
            "msg-remnawave-host-details",
            {
                "remark": "host",
                "is_disabled": 0,
                "address": "51.250.42.16",
                "port": 2222,
                "inbound_uuid": 0,
            },
        ),
        (
            "msg-remnawave-node-details",
            {
                "country": "RU",
                "name": "node",
                "is_connected": 1,
                "address": "51.250.42.16",
                "port": 2222,
                "xray_uptime": "1 day",
                "users_online": 1,
                "traffic_used": "1 GB",
                "traffic_limit": "unlimited",
            },
        ),
        (
            "msg-remnawave-inbound-details",
            {
                "tag": "inbound",
                "inbound_id": "id",
                "type": "vless",
                "network": 0,
                "port": 2222,
                "security": 0,
            },
        ),
    ],
)
def test_port_is_rendered_without_digit_grouping(
    translator: FluentTranslator,
    key: str,
    kwargs: dict[str, object],
) -> None:
    rendered = translator.get(key, **kwargs)

    assert "2 222" not in rendered
    assert "2222" in rendered
