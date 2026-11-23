import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import SecretStr

from src.application.dto.device import AuthTokenDto
from src.core.config.tobevpn import FcmServiceAccount
from src.infrastructure.database.dao.tobevpn_notification import PushDelivery
from src.infrastructure.services.fcm import FcmClient
from src.web.endpoints.device_notifications import notification_reader
from src.web.endpoints.devices import AuthRequest, DeviceAuthContext, _create_auth_token


async def test_a_linked_device_needs_session_verification_for_targeted_notifications():
    session_id = uuid4()
    users = SimpleNamespace(
        get_by_telegram_id=AsyncMock(return_value=SimpleNamespace(id=7, is_blocked=False))
    )
    auth = DeviceAuthContext(device_id="phone", session_id=session_id, telegram_id=123)
    resolve_reader = notification_reader.__dishka_orig_func__

    assert await resolve_reader(auth, users) == (None, f"s:{session_id}")
    users.get_by_telegram_id.assert_not_awaited()

    auth.verified_telegram_id = 123
    assert await resolve_reader(auth, users) == (7, "u:7")
    users.get_by_telegram_id.assert_awaited_once_with(123)

    auth.telegram_id = 456
    assert await resolve_reader(auth, users) == (None, f"s:{session_id}")


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
