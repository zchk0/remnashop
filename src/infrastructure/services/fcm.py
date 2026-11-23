import asyncio
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

import jwt
from aiohttp import ClientError, ClientSession
from loguru import logger

from src.core.config.tobevpn import FcmServiceAccount
from src.infrastructure.database.dao.tobevpn_notification import PushDelivery

OAUTH_URL = "https://oauth2.googleapis.com/token"
OAUTH_SCOPE = "https://www.googleapis.com/auth/firebase.messaging"
FCM_CHANNEL = "tobevpn_announcements"
OAUTH_RETRY_DELAY = 60


@dataclass(frozen=True)
class PushResult:
    delivered: bool = False
    unregistered: bool = False
    retry_after: float | None = None


class FcmClient:
    def __init__(self, http: ClientSession, account: FcmServiceAccount | None) -> None:
        self.http = http
        self.account = account
        self._token: str | None = None
        self._expires_at = 0.0
        self._retry_token_at = 0.0
        self._token_lock = asyncio.Lock()

    async def _access_token(self, account: FcmServiceAccount) -> str | None:
        async with self._token_lock:
            now = time.monotonic()
            if self._token is not None and now < self._expires_at:
                return self._token
            if now < self._retry_token_at:
                return None
            try:
                token, expires_in = await self._exchange_credentials(account)
            except (ClientError, TimeoutError, jwt.PyJWTError, KeyError, TypeError, ValueError):
                self._retry_token_at = time.monotonic() + OAUTH_RETRY_DELAY
                logger.warning("Could not authorize the ToBeVPN Firebase sender")
                return None
            self._expires_at = time.monotonic() + max(0, expires_in - 60)
            self._token = token
            return token

    async def _exchange_credentials(self, account: FcmServiceAccount) -> tuple[str, int]:
        now = int(time.time())
        assertion = jwt.encode(
            {
                "iss": account.client_email,
                "scope": OAUTH_SCOPE,
                "aud": OAUTH_URL,
                "iat": now,
                "exp": now + 3600,
            },
            account.private_key.get_secret_value(),
            algorithm="RS256",
            headers={"kid": account.private_key_id} if account.private_key_id else None,
        )
        async with self.http.post(
            OAUTH_URL,
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                "assertion": assertion,
            },
            allow_redirects=False,
        ) as response:
            response.raise_for_status()
            data = await response.json()
        token = data["access_token"]
        if not isinstance(token, str) or not token:
            raise ValueError("Invalid Firebase OAuth token")
        return token, int(data["expires_in"])

    async def send(self, delivery: PushDelivery) -> PushResult:
        account = self.account
        if account is None:
            return PushResult()
        ttl = int((delivery.push_expires_at - datetime.now(UTC)).total_seconds())
        if ttl <= 0:
            return PushResult()

        notification_id = str(delivery.notification_id)
        payload = {
            "message": {
                "token": delivery.token,
                "notification": {"title": delivery.title, "body": delivery.body[:180]},
                "data": {"notification_id": notification_id},
                "android": {
                    "ttl": f"{ttl}s",
                    "notification": {"channel_id": FCM_CHANNEL, "tag": notification_id},
                },
            }
        }
        url = f"https://fcm.googleapis.com/v1/projects/{account.project_id}/messages:send"

        bearer = await self._access_token(account)
        if bearer is None:
            return PushResult(retry_after=OAUTH_RETRY_DELAY)
        try:
            async with self.http.post(
                url,
                headers={"Authorization": f"Bearer {bearer}"},
                json=payload,
                allow_redirects=False,
            ) as response:
                if response.status == 200:
                    return PushResult(delivered=True)
                if response.status == 401:
                    if self._token == bearer:
                        self._expires_at = 0
                    return PushResult(retry_after=60)
                if response.status == 429 or response.status >= 500:
                    return PushResult(retry_after=_retry_after(response.headers.get("Retry-After")))
                if response.status == 404:
                    return PushResult(unregistered=_unregistered(await response.json()))
        except (ClientError, TimeoutError, ValueError):
            return PushResult(retry_after=60)
        return PushResult()


def _retry_after(header: str | None) -> float:
    if header is not None:
        try:
            return max(60, int(header))
        except ValueError:
            try:
                until = parsedate_to_datetime(header)
                return max(60, (until - datetime.now(UTC)).total_seconds())
            except (ValueError, TypeError, OverflowError):
                pass
    return 60


def _unregistered(data: Any) -> bool:
    if not isinstance(data, dict):
        return False
    error = data.get("error")
    details = error.get("details") if isinstance(error, dict) else None
    return isinstance(details, list) and any(
        isinstance(detail, dict) and detail.get("errorCode") == "UNREGISTERED" for detail in details
    )
