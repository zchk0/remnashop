import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import SecretStr

from src.application.common import TranslatorRunner
from src.application.common.uow import UnitOfWork
from src.application.dto import UserDto
from src.application.dto.device import AuthTokenDto
from src.core.config import AppConfig
from src.core.config.tobevpn import FcmServiceAccount
from src.core.constants import CONFIG_KEY, CONTAINER_KEY, USER_KEY
from src.core.enums import BroadcastAudience, Role
from src.infrastructure.database.dao.tobevpn_notification import (
    NotificationReader,
    PushDelivery,
    ToBeVpnNotificationDao,
)
from src.infrastructure.services.fcm import FcmClient
from src.telegram.routers.dashboard.broadcast.tobevpn import (
    GUESTS_ONLY_BUTTON,
    enter_content,
    publish_tobevpn,
    select_audience,
    tobevpn_audience,
    tobevpn_confirm,
)
from src.telegram.states import DashboardBroadcast
from src.web.endpoints.device_notifications import notification_reader
from src.web.endpoints.devices import AuthRequest, DeviceAuthContext, _create_auth_token


@pytest.mark.parametrize("push_enabled", [False, True])
@pytest.mark.parametrize(
    ("audience_button_id", "guests_only"),
    [(BroadcastAudience.ALL.value, False), (GUESTS_ONLY_BUTTON, True)],
)
async def test_entering_broadcast_text_loads_the_preview_with_middleware_config(
    push_enabled, audience_button_id, guests_only
):
    credentials = SecretStr("test") if push_enabled else None
    config = SimpleNamespace(tobevpn=SimpleNamespace(fcm_service_account_json=credentials))
    translator = SimpleNamespace(get=MagicMock())
    dependencies = {AppConfig: config, TranslatorRunner: translator}
    manager = SimpleNamespace(
        dialog_data={"tobevpn": {}},
        is_preview=lambda: False,
        switch_to=AsyncMock(),
        middleware_data={
            CONFIG_KEY: config,
            CONTAINER_KEY: SimpleNamespace(
                get=AsyncMock(side_effect=lambda dependency, **kwargs: dependencies[dependency])
            ),
        },
    )
    manager.middleware_data["dialog_manager"] = manager
    button = tobevpn_audience.keyboard.find(audience_button_id)
    assert button is not None
    await select_audience(None, button, manager)
    manager.switch_to.assert_awaited_once_with(DashboardBroadcast.TOBEVPN_CONTENT)
    manager.switch_to.reset_mock()

    await enter_content(SimpleNamespace(text="Title <test>\nBody & details"), None, manager)
    manager.switch_to.assert_awaited_once_with(DashboardBroadcast.TOBEVPN_PREVIEW)

    dialog = SimpleNamespace(load_data=AsyncMock(return_value={}))
    preview = await tobevpn_confirm.load_data(dialog, manager)
    assert preview["title"] == "Title &lt;test&gt;"
    assert preview["body"] == "Body &amp; details"
    assert preview["guests_only"] is guests_only
    assert preview["is_public"] is (not guests_only)
    assert preview["fcm_enabled"] is push_enabled


async def test_publishing_guest_broadcast_saves_guest_audience():
    config = SimpleNamespace(
        tobevpn=SimpleNamespace(is_enabled=True, fcm_service_account_json=None)
    )
    notifications = SimpleNamespace(publish=AsyncMock(return_value=True))
    uow = SimpleNamespace(commit=AsyncMock())
    dependencies = {
        AppConfig: config,
        TranslatorRunner: SimpleNamespace(),
        ToBeVpnNotificationDao: notifications,
        UnitOfWork: uow,
    }
    manager = SimpleNamespace(
        dialog_data={"tobevpn": {"id": str(uuid4()), "title": "Title", "body": "Body"}},
        switch_to=AsyncMock(),
        middleware_data={
            USER_KEY: UserDto(id=1, telegram_id=1, name="Admin", role=Role.OWNER),
            CONTAINER_KEY: SimpleNamespace(
                get=AsyncMock(side_effect=lambda dependency, **kwargs: dependencies[dependency])
            ),
        },
    )
    await select_audience(None, tobevpn_audience.keyboard.find(GUESTS_ONLY_BUTTON), manager)
    await publish_tobevpn(None, None, manager)

    draft = notifications.publish.await_args.args[0]
    assert draft.audience == BroadcastAudience.ALL
    assert draft.guests_only is True
    uow.commit.assert_awaited_once()
    assert manager.switch_to.await_args.args == (DashboardBroadcast.TOBEVPN_PUBLISHED,)


async def test_a_linked_device_needs_session_verification_for_targeted_notifications():
    session_id = uuid4()
    users = SimpleNamespace(
        get_by_telegram_id=AsyncMock(return_value=SimpleNamespace(id=7, is_blocked=False))
    )
    auth = DeviceAuthContext(device_id="phone", session_id=session_id, telegram_id=123)
    resolve_reader = notification_reader.__dishka_orig_func__

    assert await resolve_reader(auth, users) == NotificationReader(
        key=f"s:{session_id}", user_id=None, is_guest=False
    )
    users.get_by_telegram_id.assert_not_awaited()

    auth.verified_telegram_id = 123
    assert await resolve_reader(auth, users) == NotificationReader(
        key="u:7", user_id=7, is_guest=False
    )
    users.get_by_telegram_id.assert_awaited_once_with(123)

    auth.telegram_id = 456
    assert await resolve_reader(auth, users) == NotificationReader(
        key=f"s:{session_id}", user_id=None, is_guest=False
    )

    auth.telegram_id = None
    auth.verified_telegram_id = None
    auth.panel_user_id = 42
    assert await resolve_reader(auth, users) == NotificationReader(
        key=f"s:{session_id}", user_id=None, is_guest=True
    )


async def test_existing_auth_token_cannot_move_to_new_session_for_same_device():
    token = AuthTokenDto(device_id="phone", token="existing", device_session_id=uuid4())
    tokens = SimpleNamespace(get_by_token=AsyncMock(return_value=token), create=AsyncMock())
    with pytest.raises(HTTPException) as error:
        await _create_auth_token(
            AuthRequest(auth_token=token.token),
            DeviceAuthContext(device_id="phone", session_id=uuid4()),
            SimpleNamespace(),
            tokens,
            SimpleNamespace(),
            SimpleNamespace(),
        )
    assert error.value.status_code == 403
    tokens.create.assert_not_awaited()


async def test_fcm_push_contains_preview_and_the_id_needed_to_open_the_announcement():
    http = MagicMock()
    http.post.return_value.__aenter__.return_value = SimpleNamespace(status=200)
    fcm = FcmClient(
        http,
        FcmServiceAccount(
            project_id="tobevpn-test",
            client_email="push@example.com",
            private_key=SecretStr("unused"),
        ),
    )
    fcm._access_token = AsyncMock(return_value="test-access-token")
    delivery = PushDelivery(
        id=1,
        attempts=1,
        device_id="phone",
        session_id=uuid4(),
        notification_id=uuid4(),
        title="Service notice",
        body="x" * 300,
        push_expires_at=datetime.now(UTC) + timedelta(hours=1),
        token="test-firebase-token",
    )

    assert (await fcm.send(delivery)).delivered
    call = http.post.call_args
    assert call.args == ("https://fcm.googleapis.com/v1/projects/tobevpn-test/messages:send",)
    message = call.kwargs["json"]["message"]
    assert message["notification"] == {"title": delivery.title, "body": "x" * 180}
    assert message["data"] == {"notification_id": str(delivery.notification_id)}
    assert message["android"]["notification"] == {
        "channel_id": "tobevpn_announcements",
        "tag": str(delivery.notification_id),
    }


async def test_concurrent_pushes_share_oauth_backoff_when_firebase_is_unavailable():
    account = FcmServiceAccount(
        project_id="tobevpn-test",
        client_email="push@example.com",
        private_key=SecretStr("unused"),
    )
    fcm = FcmClient(MagicMock(), account)
    fcm._exchange_credentials = AsyncMock(side_effect=TimeoutError)

    results = await asyncio.gather(*(fcm._access_token(account) for _ in range(16)))
    assert results == [None] * 16
    fcm._exchange_credentials.assert_awaited_once_with(account)
