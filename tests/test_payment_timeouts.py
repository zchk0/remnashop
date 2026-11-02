from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fluent_compiler.bundle import FluentBundle
from fluentogram.translator import FluentTranslator
from pydantic import SecretStr
from sqlalchemy import create_engine, text

from src.application.dto import PaymentGatewayDto
from src.application.dto.payment_gateway import FlippayGatewaySettingsDto
from src.application.use_cases.gateways.commands.configuration import (
    ResetPaymentGatewaySettingsDto,
    ResetPaymentGatewaySettingsField,
    UpdatePaymentGatewaySettings,
    UpdatePaymentGatewaySettingsDto,
)
from src.application.use_cases.misc.commands.maintenance import CancelOldTransactions
from src.core.constants import CONTAINER_KEY
from src.core.enums import Currency, PaymentGatewayType
from src.infrastructure.database.dao.transaction import TransactionDaoImpl
from src.infrastructure.di.providers.retort import RetortProvider
from src.telegram.routers.dashboard.remnashop.gateways.dialog import gateway_settings
from src.telegram.routers.dashboard.remnashop.gateways.getters import field_getter


def gateway(*, minutes=None, active=True):
    return PaymentGatewayDto(
        id=1,
        type=PaymentGatewayType.FLIPPAY,
        currency=Currency.RUB,
        is_active=active,
        settings=FlippayGatewaySettingsDto(
            api_key=SecretStr("pk_test"),
            api_secret=SecretStr("sk_test"),
            webhook_secret=SecretStr("wh_test"),
            **({"payment_timeout_minutes": minutes} if minutes is not None else {}),
        ),
    )


@pytest.mark.parametrize("minutes", [1, 30, 60, 90])
async def test_admin_can_set_timeout_and_reset_to_sixty(minutes):
    dto = gateway()
    assert dto.settings.payment_timeout_minutes == 60
    dao = SimpleNamespace(get_by_id=AsyncMock(return_value=dto), update=AsyncMock())
    uow = AsyncMock()
    update = UpdatePaymentGatewaySettings(uow, dao, RetortProvider().get_retort())
    await update.system(UpdatePaymentGatewaySettingsDto(1, "payment_timeout_minutes", str(minutes)))
    assert dto.settings.payment_timeout_minutes == minutes
    assert dto.is_active and dto.settings.is_configured
    reset = ResetPaymentGatewaySettingsField(uow, dao)
    assert not await reset.system(ResetPaymentGatewaySettingsDto(1, "payment_timeout_minutes"))
    assert dto.settings.payment_timeout_minutes == 60
    assert dto.is_active and dto.settings.is_configured


@pytest.mark.parametrize("value", ["0", "-1", "1.5", "abc", ""])
async def test_invalid_timeout_does_not_change_settings(value):
    dto = gateway(minutes=60)
    dao = SimpleNamespace(get_by_id=AsyncMock(return_value=dto), update=AsyncMock())
    update = UpdatePaymentGatewaySettings(AsyncMock(), dao, RetortProvider().get_retort())
    with pytest.raises(ValueError):
        await update.system(UpdatePaymentGatewaySettingsDto(1, "payment_timeout_minutes", value))
    assert dto.settings.payment_timeout_minutes == 60
    dao.update.assert_not_awaited()


@pytest.mark.parametrize("active", [True, False])
async def test_cleanup_reads_current_timeout_even_for_disabled_gateway(active):
    dto = gateway(minutes=90, active=active)
    dao = SimpleNamespace(cancel_old=AsyncMock(return_value=0))
    gateway_dao = SimpleNamespace(get_by_type=AsyncMock(return_value=dto))
    cleanup = CancelOldTransactions(AsyncMock(), dao, gateway_dao)
    await cleanup.system()
    dao.cancel_old.assert_awaited_once_with(gateway_timeouts={PaymentGatewayType.FLIPPAY: 90})
    # The next run applies an edited setting to payments that are still pending.
    dto.settings.payment_timeout_minutes = 5
    await cleanup.system()
    dao.cancel_old.assert_awaited_with(gateway_timeouts={PaymentGatewayType.FLIPPAY: 5})


@pytest.mark.parametrize("missing_settings", [True, False])
async def test_missing_gateway_or_settings_uses_standard_timeout(missing_settings):
    dto = gateway()
    dto.settings = None
    dao = SimpleNamespace(cancel_old=AsyncMock(return_value=0))
    cleanup = CancelOldTransactions(
        AsyncMock(),
        dao,
        SimpleNamespace(get_by_type=AsyncMock(return_value=dto if missing_settings else None)),
    )
    await cleanup.system()
    dao.cancel_old.assert_awaited_once_with(gateway_timeouts={})


@pytest.mark.parametrize(
    "timeouts,canceled_ids",
    [
        (None, {2, 3, 4, 6, 7}),
        ({PaymentGatewayType.FLIPPAY: 30}, {2, 3, 4, 6, 7}),
        ({PaymentGatewayType.FLIPPAY: 60}, {4, 6, 7}),
        ({PaymentGatewayType.FLIPPAY: 5}, {1, 2, 3, 4, 6, 7}),
    ],
)
async def test_cleanup_executes_gateway_specific_deadlines_without_touching_terminal_statuses(
    monkeypatch, timeouts, canceled_ids
):
    now = datetime(2026, 11, 2, 12, tzinfo=UTC)
    monkeypatch.setattr("src.infrastructure.database.dao.transaction.datetime_now", lambda: now)
    rows = [
        (1, "FLIPPAY", "PENDING", 29),
        (2, "FLIPPAY", "PENDING", 31),
        (3, "FLIPPAY", "PENDING", 60),
        (4, "FLIPPAY", "PENDING", 61),
        (5, "PLATEGA", "PENDING", 29),
        (6, "PLATEGA", "PENDING", 31),
        (7, "YOOKASSA", "PENDING", 31),
        (8, "FLIPPAY", "COMPLETED", 61),
        (9, "FLIPPAY", "FAILED", 61),
        (10, "FLIPPAY", "REFUNDED", 61),
    ]
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        # SQLite timestamps are already UTC; supply PostgreSQL's onupdate helper.
        connection.connection.driver_connection.create_function(
            "timezone", 2, lambda zone, timestamp: timestamp
        )
        connection.exec_driver_sql(
            "CREATE TABLE transactions (id INTEGER PRIMARY KEY, gateway_type TEXT, "
            "status TEXT, created_at DATETIME, updated_at DATETIME)"
        )
        for row_id, kind, status, age in rows:
            connection.execute(
                text(
                    "INSERT INTO transactions (id, gateway_type, status, created_at) "
                    "VALUES (:id, :kind, :status, :created_at)"
                ),
                {
                    "id": row_id,
                    "kind": kind,
                    "status": status,
                    "created_at": (now - timedelta(minutes=age))
                    .replace(tzinfo=None)
                    .isoformat(sep=" ", timespec="microseconds"),
                },
            )
        dao = TransactionDaoImpl.__new__(TransactionDaoImpl)
        # Execute the actual DAO UPDATE, using SQLite for the portable SQL predicates.
        dao.session = SimpleNamespace(execute=AsyncMock(side_effect=connection.execute))
        assert await dao.cancel_old(gateway_timeouts=timeouts) == len(canceled_ids)
        actual = dict(connection.execute(text("SELECT id, status FROM transactions")).all())
        for row_id, _, status, _ in rows:
            assert actual[row_id] == ("CANCELED" if row_id in canceled_ids else status)
    engine.dispose()


def translator():
    return FluentTranslator(
        locale="ru",
        translator=FluentBundle.from_string(
            locale="ru",
            text="\n".join(
                Path(f"assets/translations/ru/{name}.ftl").read_text("utf-8")
                for name in ("buttons", "messages", "utils")
            ),
            use_isolating=False,
        ),
    )


async def test_settings_show_timeout_minutes_and_input_help():
    dto = gateway(minutes=90)
    i18n = translator()
    manager = SimpleNamespace(
        dialog_data={"gateway_id": 1, "selected_field": "payment_timeout_minutes"},
        middleware_data={CONTAINER_KEY: SimpleNamespace(get=AsyncMock(return_value=i18n))},
        is_preview=lambda: False,
    )
    selection = gateway_settings.find("setting")
    keyboard = await selection.render_keyboard(
        {"settings": [item for item in dto.settings.as_list if item["field"] != "display_name"]},
        manager,
    )
    assert any("Ожидание: 90 мин." in button.text for row in keyboard for button in row)
    data = await field_getter.__dishka_orig_func__(
        manager, SimpleNamespace(get_by_id=AsyncMock(return_value=dto))
    )
    rendered = i18n.get("msg-gateways-field", **data)
    assert "Текущее значение: 90 мин." in rendered
    assert "Значение по умолчанию: 60 мин." in rendered
    assert "целое число больше нуля" in rendered
