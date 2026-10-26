import hmac
from decimal import Decimal
from typing import Any, Final, Optional, Union, cast
from uuid import UUID

import orjson
from aiogram import Bot
from fastapi import Request
from httpx import AsyncClient, HTTPStatusError
from loguru import logger

from src.application.dto import PaymentGatewayDto, PaymentResultDto
from src.application.dto.payment_gateway import PlategaGatewaySettingsDto
from src.core.config import AppConfig
from src.core.enums import TransactionStatus

from .base import BasePaymentGateway


# https://docs.platega.io/
class PlategaGateway(BasePaymentGateway):
    _client: AsyncClient

    API_BASE: Final[str] = "https://app.platega.io"
    DEFAULT_MULTI_METHOD_ENDPOINT: Final[str] = "v2/transaction/process"
    DEFAULT_SINGLE_METHOD_ENDPOINT: Final[str] = "transaction/process"

    def __init__(self, gateway: PaymentGatewayDto, bot: Bot, config: AppConfig) -> None:
        super().__init__(gateway, bot, config)

        if not isinstance(self.data.settings, PlategaGatewaySettingsDto):
            raise TypeError(
                f"Invalid settings type: expected {PlategaGatewaySettingsDto.__name__}, "
                f"got {type(self.data.settings).__name__}"
            )

        self.settings = cast(PlategaGatewaySettingsDto, self.data.settings)
        if self.settings.merchant_id is None or self.settings.api_key is None:
            raise ValueError("Platega gateway is not configured")

        self.merchant_id = self.settings.merchant_id
        self.api_key = self.settings.api_key.get_secret_value()

        self._client = self._make_client(
            base_url=self.API_BASE,
            headers={
                "X-MerchantId": self.merchant_id,
                "X-Secret": self.api_key,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        self.selected_payment_method: Optional[str] = None
        self.recurring_webhook: dict[str, Any] | None = None

    @staticmethod
    def subscription_interval(days: int) -> tuple[int, int]:
        if days > 0 and days % 30 == 0 and days // 30 <= 12:
            return 3, days // 30
        if days > 0 and days % 365 == 0 and days // 365 <= 3:
            return 4, days // 365
        if 1 <= days <= 31:
            return 1, days
        if days > 0 and days % 7 == 0 and days // 7 <= 4:
            return 2, days // 7
        raise ValueError("This duration is not supported by Platega subscriptions")

    async def create_subscription(
        self, amount: Decimal, details: str, duration: int
    ) -> PaymentResultDto:
        if amount <= 0 or amount != amount.to_integral_value():
            raise ValueError("Platega subscriptions require a positive integer RUB amount")
        interval, count = self.subscription_interval(duration)
        response = await self._client.post(
            self.DEFAULT_SINGLE_METHOD_ENDPOINT,
            json={
                "paymentMethod": 6,
                "paymentDetails": {
                    "amount": int(amount),
                    "currency": "RUB",
                    "interval": interval,
                    "intervalCount": count,
                },
                "description": details,
            },
        )
        response.raise_for_status()
        return self._get_payment_data(response.json())

    async def get_subscription(self, subscription_id: UUID) -> dict[str, Any]:
        response = await self._client.get(f"subscription/{subscription_id}")
        response.raise_for_status()
        return cast(dict[str, Any], response.json())

    async def cancel_subscription(self, subscription_id: UUID) -> None:
        response = await self._client.post(f"subscription/{subscription_id}/cancel")
        response.raise_for_status()

    async def handle_create_payment(self, amount: Decimal, details: str) -> PaymentResultDto:
        payload = await self._create_payment_payload(amount, details)
        logger.debug(f"Creating payment payload: {payload}")
        endpoint = (
            self.DEFAULT_SINGLE_METHOD_ENDPOINT
            if self.settings.payment_method is not None
            else self.DEFAULT_MULTI_METHOD_ENDPOINT
        )

        try:
            response = await self._client.post(endpoint, json=payload)
            response.raise_for_status()
            data = orjson.loads(response.content)
            return self._get_payment_data(data)

        except HTTPStatusError as e:
            logger.error(
                f"HTTP error creating payment. "
                f"Status: '{e.response.status_code}', Body: {e.response.text}"
            )
            raise
        except (KeyError, orjson.JSONDecodeError) as e:
            logger.error(f"Failed to parse response. Error: {e}")
            raise
        except Exception as e:
            logger.exception(f"An unexpected error occurred while creating payment: {e}")
            raise

    async def handle_webhook(self, request: Request) -> Union[tuple[UUID, TransactionStatus], None]:
        logger.debug(f"Received {self.__class__.__name__} webhook request")

        raw_body = await request.body()
        self.recurring_webhook = None
        self.selected_payment_method = None
        if not self._verify_webhook(request):
            raise PermissionError("Webhook verification failed")

        webhook_data = orjson.loads(raw_body)
        if not isinstance(webhook_data, dict):
            raise ValueError("Invalid Platega callback")
        # Platega documents PascalCase for subscriptions and camelCase for ordinary payments.
        webhook_data = {key[0].lower() + key[1:]: value for key, value in webhook_data.items()}
        status = str(webhook_data.get("status", "")).upper()
        webhook_data["status"] = status
        if webhook_data.get("subscriptionId") or status.startswith("SUBSCRIPTION_"):
            subscription_id = webhook_data.get("subscriptionId") or webhook_data.get("id")
            UUID(str(subscription_id))
            webhook_data["subscriptionId"] = str(subscription_id)
            self.recurring_webhook = webhook_data
            return None

        payment_id_str = webhook_data.get("id")
        if not payment_id_str:
            raise ValueError("Required field 'id' is missing")

        payment_id = UUID(payment_id_str)
        self.selected_payment_method = self._normalize_payment_method(
            webhook_data.get("paymentMethod")
        )

        match status:
            case "CONFIRMED":
                transaction_status = TransactionStatus.COMPLETED
            case "CANCELED":
                transaction_status = TransactionStatus.CANCELED
            case "CHARGEBACKED":
                transaction_status = TransactionStatus.REFUNDED
            case _:
                raise ValueError(f"Unsupported status: {status}")

        return payment_id, transaction_status

    async def _create_payment_payload(self, amount: Decimal, details: str) -> dict[str, Any]:
        if self.settings.payment_method == 6:
            raise ValueError("Enable the separate autopay option instead of payment_method=6")
        payload: dict[str, Any] = {
            "paymentDetails": {
                "amount": float(amount),
                "currency": self.data.currency.value,
            },
            "description": details,
            "return": await self._get_bot_redirect_url(),
            "failedUrl": await self._get_bot_redirect_url(),
        }
        if self.settings.payment_method is not None:
            payload["paymentMethod"] = self.settings.payment_method

        return payload

    def _get_payment_data(self, data: dict[str, Any]) -> PaymentResultDto:
        transaction_id_str = data.get("transactionId")
        if not transaction_id_str:
            raise KeyError("Invalid response from API: missing 'transactionId'")

        payment_url = data.get("redirect") or data.get("url")
        if not payment_url:
            raise KeyError("Invalid response from API: missing 'redirect' or 'url'")

        return PaymentResultDto(id=UUID(transaction_id_str), url=str(payment_url))

    @staticmethod
    def _normalize_payment_method(value: Any) -> str | None:
        if value is None:
            return None

        payment_method = str(value).strip()
        return payment_method or None

    def _verify_webhook(self, request: Request) -> bool:
        merchant_id = request.headers.get("X-MerchantId")
        secret = request.headers.get("X-Secret")

        if not merchant_id or not secret:
            logger.warning("Webhook is missing X-MerchantId or X-Secret headers")
            return False

        merchant_id_ok = hmac.compare_digest(merchant_id, self.merchant_id)
        secret_ok = hmac.compare_digest(secret, self.api_key)

        if not merchant_id_ok or not secret_ok:
            logger.warning("Invalid Platega webhook credentials")
            return False

        return True
