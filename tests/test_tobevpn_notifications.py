import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from aiogram.enums import ButtonStyle
from aiogram_dialog import ShowMode
from fastapi import HTTPException, Response
from pydantic import SecretStr

from src.application.common import Notifier, TranslatorRunner
from src.application.common.dao import BroadcastDao
from src.application.common.uow import UnitOfWork
from src.application.dto import UserDto
from src.application.dto.device import AuthTokenDto
from src.core.config import AppConfig
from src.core.config.tobevpn import FcmServiceAccount
from src.core.constants import ASSETS_DIR, CONFIG_KEY, CONTAINER_KEY, USER_KEY
from src.core.enums import BroadcastAudience, BroadcastStatus, Role
from src.infrastructure.database.dao.tobevpn_notification import (
    NotificationReader,
    PushDelivery,
    ToBeVpnNotificationDao,
)
from src.infrastructure.di.providers.retort import RetortProvider
from src.infrastructure.services.fcm import FcmClient
from src.infrastructure.services.i18n import LayeredFileStorage
from src.infrastructure.services.translator import TranslatorRunnerImpl
from src.telegram.routers.dashboard.broadcast.dialog import broadcast
from src.telegram.routers.dashboard.broadcast.dialog import list as broadcast_list
from src.telegram.routers.dashboard.broadcast.tobevpn import (
    GUESTS_ONLY_BUTTON,
    enter_content,
    publish_tobevpn,
    select_audience,
    tobevpn_audience,
    tobevpn_confirm,
    tobevpn_delete,
    tobevpn_view,
)
from src.telegram.states import DashboardBroadcast
from src.web.endpoints.device_notifications import get_notification, notification_reader
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
    translator = SimpleNamespace(get=MagicMock(side_effect=lambda key, **kwargs: key))
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

    invalid_message = SimpleNamespace(text="Only a title", answer=AsyncMock())
    await enter_content(invalid_message, None, manager)
    invalid_message.answer.assert_awaited_once()
    assert manager.show_mode is ShowMode.NO_UPDATE
    manager.switch_to.assert_not_awaited()

    await enter_content(SimpleNamespace(text="Title <test>\nBody & details"), None, manager)
    manager.switch_to.assert_awaited_once_with(
        DashboardBroadcast.TOBEVPN_PREVIEW, show_mode=ShowMode.DELETE_AND_SEND
    )

    dialog = SimpleNamespace(load_data=AsyncMock(return_value={}))
    preview = await tobevpn_confirm.load_data(dialog, manager)
    assert preview["title"] == "Title &lt;test&gt;"
    assert preview["body"] == "Body &amp; details"
    assert preview["guests_only"] is guests_only
    assert preview["is_public"] is (not guests_only)
    assert preview["fcm_enabled"] is push_enabled
    keyboard = await tobevpn_confirm.keyboard.render_keyboard(preview, manager)
    publish_button = next(
        button for row in keyboard for button in row if button.callback_data == "publish"
    )
    assert publish_button.style == ButtonStyle.SUCCESS


async def test_publishing_guest_broadcast_saves_guest_audience_and_channel_action():
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
    dialog = SimpleNamespace()
    await tobevpn_confirm.process_callback(SimpleNamespace(data="plans"), dialog, manager)
    assert manager.dialog_data["tobevpn"]["action"] == "plans"
    await tobevpn_confirm.process_callback(SimpleNamespace(data="channel"), dialog, manager)
    assert manager.dialog_data["tobevpn"]["action"] == "channel"
    await tobevpn_confirm.process_callback(SimpleNamespace(data="channel"), dialog, manager)
    assert manager.dialog_data["tobevpn"]["action"] is None
    await tobevpn_confirm.process_callback(SimpleNamespace(data="channel"), dialog, manager)
    await publish_tobevpn(None, None, manager)

    draft = notifications.publish.await_args.args[0]
    assert draft.audience == BroadcastAudience.ALL
    assert draft.guests_only is True
    assert draft.action == "channel"
    uow.commit.assert_awaited_once()
    assert manager.switch_to.await_args.args == (DashboardBroadcast.TOBEVPN_PUBLISHED,)


@pytest.mark.parametrize(
    ("button", "action"), [(None, None), ("plans", "plans"), ("channel", "url")]
)
async def test_notification_details_use_a_generic_url_action_for_external_buttons(button, action):
    item = SimpleNamespace(
        id=uuid4(), title="Title", body="Body", published_at=datetime.now(UTC), action=button
    )
    notifications = SimpleNamespace(get_visible=AsyncMock(return_value=(item, None)))
    reader = NotificationReader(key="u:1", user_id=1, is_guest=False)
    response = await get_notification.__dishka_orig_func__(
        item.id, reader, notifications, Response()
    )

    result = response.model_dump(exclude_unset=True)
    assert result["success"] is True
    assert result["data"]["action"] == action
    assert result["data"]["read_at"] is None
    if action == "url":
        assert result["data"]["action_url"] == "https://t.me/meow_meow_vpn"
        assert result["data"]["action_label"] == "Перейти в канал"
    else:
        assert "action_url" not in result["data"]
        assert "action_label" not in result["data"]


async def test_broadcast_history_opens_tobevpn_and_telegram_entries():
    now = datetime.now(UTC)
    publication_id, task_id = uuid4(), uuid4()
    publication = SimpleNamespace(
        title="Title <test>",
        body="Body & details",
        published_at=now,
        is_public=False,
        guests_only=False,
    )
    notifications = SimpleNamespace(
        list_published=AsyncMock(return_value=[(publication_id, publication.title, now)]),
        get_publication=AsyncMock(return_value=(publication, 2, 3)),
    )
    telegram = SimpleNamespace(get_all=AsyncMock(return_value=[]))
    translator = SimpleNamespace(get=lambda key, **kwargs: key)
    dependencies = {
        BroadcastDao: telegram,
        Notifier: SimpleNamespace(notify_user=AsyncMock()),
        ToBeVpnNotificationDao: notifications,
        TranslatorRunner: translator,
    }
    manager = SimpleNamespace(
        dialog_data={},
        is_preview=lambda: False,
        switch_to=AsyncMock(),
        middleware_data={
            USER_KEY: UserDto(id=1, telegram_id=1, name="Admin", role=Role.OWNER),
            CONTAINER_KEY: SimpleNamespace(
                get=AsyncMock(side_effect=lambda dependency, **kwargs: dependencies[dependency])
            ),
        },
    )
    manager.middleware_data["dialog_manager"] = manager
    dialog = SimpleNamespace(load_data=AsyncMock(side_effect=lambda manager: {}))
    await broadcast.process_callback(SimpleNamespace(data="list"), dialog, manager)
    manager.switch_to.assert_awaited_once_with(state=DashboardBroadcast.LIST)

    telegram.get_all.return_value = [
        SimpleNamespace(
            task_id=task_id, status=BroadcastStatus.COMPLETED, created_at=now - timedelta(days=1)
        )
    ]
    data = await broadcast_list.load_data(dialog, manager)
    picker = broadcast_list.keyboard.find("broadcast")
    assert picker is not None
    buttons = [button for row in await picker.render_keyboard(data, manager) for button in row]
    assert [button.text for button in buttons] == [
        "btn-tobevpn-broadcast.title",
        "btn-broadcast.title",
    ]
    await broadcast_list.process_callback(
        SimpleNamespace(data=buttons[0].callback_data), dialog, manager
    )
    manager.switch_to.assert_awaited_with(state=DashboardBroadcast.TOBEVPN_VIEW)
    view = await tobevpn_view.load_data(dialog, manager)
    notifications.get_publication.assert_awaited_once_with(publication_id)
    assert view["read_count"] == 2
    assert view["recipient_count"] == 3
    assert view["title"] == "Title &lt;test&gt;"
    assert view["body"] == "Body &amp; details"
    notifications.get_publication.return_value = None
    assert await tobevpn_view.load_data(dialog, manager) == {"publication_available": False}

    await broadcast_list.process_callback(
        SimpleNamespace(data=buttons[1].callback_data), dialog, manager
    )
    manager.switch_to.assert_awaited_with(state=DashboardBroadcast.VIEW)
    assert manager.dialog_data["task_id"] == task_id


@pytest.mark.parametrize(
    ("locale", "confirm_label"), [("ru", "✅ Да, удалить"), ("en", "✅ Yes, delete")]
)
async def test_tobevpn_delete_confirms_the_selected_publication_and_checks_permission(
    tmp_path, locale, confirm_label
):
    notification_id = uuid4()
    publication = SimpleNamespace(
        title="Release",
        body="Details",
        published_at=datetime.now(UTC),
        is_public=True,
        guests_only=False,
    )
    notifications = SimpleNamespace(
        get_publication=AsyncMock(return_value=(publication, 0, 0)),
        delete_publication=AsyncMock(),
    )
    uow = SimpleNamespace(commit=AsyncMock())
    translations = LayeredFileStorage(tmp_path, ASSETS_DIR / "translations")
    i18n = TranslatorRunnerImpl(
        translations.get_translators_for_language(locale), RetortProvider().get_retort()
    )
    dependencies = {
        ToBeVpnNotificationDao: notifications,
        UnitOfWork: uow,
        TranslatorRunner: i18n,
    }
    owner = UserDto(id=1, telegram_id=1, name="Owner", role=Role.OWNER)
    manager = SimpleNamespace(
        dialog_data={"tobevpn_notification_id": str(notification_id)},
        is_preview=lambda: False,
        switch_to=AsyncMock(),
        middleware_data={
            USER_KEY: owner,
            CONTAINER_KEY: SimpleNamespace(
                get=AsyncMock(side_effect=lambda dependency, **kwargs: dependencies[dependency])
            ),
        },
    )
    manager.middleware_data["dialog_manager"] = manager
    dialog = SimpleNamespace(load_data=AsyncMock(side_effect=lambda manager: {}))
    await tobevpn_view.process_callback(SimpleNamespace(data="delete"), dialog, manager)
    manager.switch_to.assert_awaited_once_with(DashboardBroadcast.TOBEVPN_DELETE, show_mode=None)
    notifications.delete_publication.assert_not_awaited()

    confirm_data = await tobevpn_delete.load_data(dialog, manager)
    assert "<b>Release</b>" in await tobevpn_delete.render_text(confirm_data, manager)
    [[button], [cancel]] = await tobevpn_delete.keyboard.render_keyboard(confirm_data, manager)
    assert button.text == confirm_label
    assert button.callback_data == f"delete_confirm:{notification_id}"
    assert cancel.callback_data == "cancel"
    confirm = tobevpn_delete.keyboard.find("delete_confirm")
    assert confirm is not None

    stale = SimpleNamespace(data=f"delete_confirm:{uuid4()}")
    await tobevpn_delete.process_callback(stale, dialog, manager)
    manager.middleware_data[USER_KEY] = UserDto(
        id=2, telegram_id=2, name="Viewer", role=Role.PREVIEW
    )
    preview_data = await tobevpn_delete.load_data(dialog, manager)
    assert not await confirm.render_keyboard(preview_data, manager)
    callback = SimpleNamespace(data=button.callback_data, answer=AsyncMock())
    await tobevpn_delete.process_callback(callback, dialog, manager)
    notifications.delete_publication.assert_not_awaited()
    uow.commit.assert_not_awaited()

    manager.middleware_data[USER_KEY] = owner
    await tobevpn_delete.process_callback(callback, dialog, manager)
    notifications.delete_publication.assert_awaited_once_with(notification_id)
    uow.commit.assert_awaited_once()
    manager.switch_to.assert_awaited_with(DashboardBroadcast.LIST)
    callback.answer.assert_awaited_once_with(i18n.get("msg-tobevpn-broadcast-deleted"))


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
