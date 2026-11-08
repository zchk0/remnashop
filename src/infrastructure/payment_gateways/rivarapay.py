import asyncio
import hashlib
import hmac
import re
import time
from decimal import Decimal, InvalidOperation
from typing import Any, Final
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import orjson
from aiogram import Bot
from fastapi import Request
from httpx import Response, TransportError

from src.application.dto import PaymentGatewayDto, PaymentResultDto, TransactionDto
from src.application.dto.payment_gateway import RivaraGatewaySettingsDto
from src.core.config import AppConfig
from src.core.enums import Currency, PaymentGatewayType, TransactionStatus

from .base import BasePaymentGateway


class RivaraGateway(BasePaymentGateway):
    """Rivara Pay v1 API, specification dated 2026-11-06."""

    API_BASE: Final[str] = "https://api.rivarapay.io/api/v1/"
    PAYMENT_EVENTS: Final[dict[str, tuple[str, TransactionStatus]]] = {
        "payment.paid": ("paid", TransactionStatus.COMPLETED),
        "payment.canceled": ("canceled", TransactionStatus.CANCELED),
        # An expired intent can still be paid later.
        "payment.expired": ("expired", TransactionStatus.FAILED),
    }

    def __init__(self, gateway: PaymentGatewayDto, bot: Bot, config: AppConfig) -> None:
        super().__init__(gateway, bot, config)
        if not isinstance(gateway.settings, RivaraGatewaySettingsDto):
            raise TypeError("Invalid Rivara Pay settings")
        if not gateway.settings.is_configured or gateway.currency != Currency.RUB:
            raise ValueError("Rivara Pay requires configured credentials and RUB currency")
        self.settings = gateway.settings
        assert self.settings.api_key is not None and self.settings.webhook_secret is not None
        key = self.settings.api_key.get_secret_value()
        if not key.startswith(("live_", "test_")):
            raise ValueError("Invalid Rivara Pay API key prefix")
        self.is_test_mode = key.startswith("test_")
        self._webhook_secret = self.settings.webhook_secret.get_secret_value().encode()
        self._client = self._make_client(
            base_url=self.API_BASE,
            headers={
                "X-API-Key": key,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )

    @staticmethod
    def _amount(value: Any) -> Decimal:
        try:
            amount = Decimal(str(value))
            if not amount.is_finite() or amount <= 0 or amount != amount.quantize(Decimal("0.01")):
                raise ValueError("Invalid Rivara Pay amount")
        except InvalidOperation as error:
            raise ValueError("Invalid Rivara Pay amount") from error
        return amount

    @staticmethod
    def _provider_id(value: Any) -> str:
        if not isinstance(value, str) or not re.fullmatch(r"pi_[A-Za-z0-9]+", value):
            raise ValueError("Invalid Rivara Pay payment ID")
        return value

    async def handle_create_payment(
        self,
        amount: Decimal,
        details: str,
        *,
        payment_method: str | None = None,
        customer_email: str | None = None,
    ) -> PaymentResultDto:
        amount = self._amount(amount)
        method = self.settings.get_payment_method(payment_method)
        if not customer_email:
            raise ValueError("Rivara Pay requires a customer email")
        order_id = uuid4()
        payload: dict[str, Any] = {
            # A decimal string means minor units in this API. Avoid a float conversion.
            "amount": str(int(amount * 100)),
            "currency": self.data.currency.value,
            "merchantOrderId": str(order_id),
            "customerEmail": customer_email,
            "description": details[:500],
            "returnUrl": await self._get_bot_redirect_url(),
        }
        if method.id != "ALL":
            payload["allowedMethods"] = [method.id]
        response = await self._create_intent(payload, order_id)
        data = response.json()
        if (
            not isinstance(data, dict)
            or data.get("merchantOrderId") != str(order_id)
            or data.get("livemode") is not (not self.is_test_mode)
        ):
            raise ValueError("Rivara Pay creation response order or mode mismatch")
        self._validate_rest_amount(data, amount, self.data.currency)
        provider_id = self._provider_id(data.get("id"))
        url = data.get("checkoutUrl")
        if (
            not isinstance(url, str)
            or urlsplit(url).scheme != "https"
            or not urlsplit(url).hostname
        ):
            raise ValueError("Invalid Rivara Pay checkout URL")
        return PaymentResultDto(id=order_id, url=url, provider_payment_id=provider_id)

    async def _create_intent(self, payload: dict[str, Any], order_id: UUID) -> Response:
        for attempt in range(3):
            try:
                response = await self._client.post(
                    "payment-intents", json=payload, headers={"Idempotency-Key": str(order_id)}
                )
            except TransportError:
                if attempt == 2:
                    raise
            else:
                if response.status_code != 429 and response.status_code < 500 or attempt == 2:
                    response.raise_for_status()
                    return response
            # Retries preserve both the order ID and payload, including after a timeout.
            await asyncio.sleep(0.2 * 2**attempt)
        raise RuntimeError("Rivara Pay creation retries exhausted")

    async def get_payment(self, provider_payment_id: str) -> dict[str, Any]:
        response = await self._client.get(
            f"payment-intents/{self._provider_id(provider_payment_id)}"
        )
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("Invalid Rivara Pay transaction response")
        return data

    async def handle_webhook(self, request: Request) -> tuple[UUID, TransactionStatus] | None:
        raw_body = await request.body()
        timestamp = request.headers.get("X-Timestamp", "")
        if not re.fullmatch(r"[0-9]{1,12}", timestamp) or abs(time.time() - int(timestamp)) > 300:
            raise ValueError("Invalid or expired Rivara Pay webhook timestamp")
        signature = request.headers.get("X-Signature", "")
        expected = hmac.new(
            self._webhook_secret, timestamp.encode() + b"." + raw_body, hashlib.sha256
        ).hexdigest()
        if not re.fullmatch(r"[0-9a-fA-F]{64}", signature) or not hmac.compare_digest(
            expected, signature.lower()
        ):
            raise PermissionError("Invalid Rivara Pay webhook signature")
        event_id = request.headers.get("X-Event-Id", "")
        if not event_id or len(event_id) > 200:
            raise ValueError("Invalid Rivara Pay webhook event ID")
        data = orjson.loads(raw_body)
        if not isinstance(data, dict) or not isinstance(data.get("event_type"), str):
            raise ValueError("Invalid Rivara Pay webhook event")
        event = self.PAYMENT_EVENTS.get(data["event_type"])
        if event is None:
            # Refund and conversion events have a different shape; they cannot fulfil orders.
            return None
        if data.get("status") != event[0] or type(data.get("test")) is not bool:
            raise ValueError("Invalid Rivara Pay webhook status or mode")
        self._provider_id(data.get("payment_id"))
        self._amount(data.get("amount"))
        if data.get("currency") != self.data.currency.value:
            raise ValueError("Invalid Rivara Pay webhook currency")
        return UUID(str(data.get("order_id"))), event[1]

    @classmethod
    def _validate_rest_amount(
        cls, data: dict[str, Any], amount: Decimal, currency: Currency
    ) -> None:
        money = data.get("amount")
        if (
            not isinstance(money, dict)
            or not isinstance(money.get("amount"), str)
            or not re.fullmatch(r"[0-9]+", money["amount"])
            or Decimal(money["amount"]) != amount * 100
            or money.get("currency") != currency.value
        ):
            raise ValueError("Rivara Pay transaction amount or currency mismatch")

    def validate_payment_data(self, data: dict[str, Any], transaction: TransactionDto) -> None:
        if (
            transaction.gateway_type != PaymentGatewayType.RIVARAPAY
            or transaction.currency != Currency.RUB
            or data.get("id") != transaction.provider_payment_id
            or data.get("merchantOrderId") != str(transaction.payment_id)
            or data.get("livemode") is not (not self.is_test_mode)
            or (self.is_test_mode and not transaction.is_test)
        ):
            raise ValueError("Rivara Pay transaction ID, gateway or mode mismatch")
        self._validate_rest_amount(data, transaction.pricing.final_amount, transaction.currency)

    async def validate_webhook_transaction(
        self, request: Request, transaction: TransactionDto
    ) -> None:
        data = orjson.loads(await request.body())
        if (
            transaction.gateway_type != PaymentGatewayType.RIVARAPAY
            or transaction.currency != Currency.RUB
            or data.get("payment_id") != transaction.provider_payment_id
            or data.get("order_id") != str(transaction.payment_id)
            or data.get("currency") != transaction.currency.value
            or self._amount(data.get("amount")) != transaction.pricing.final_amount
            or data.get("test") is not self.is_test_mode
            or (data.get("test") and not transaction.is_test)
        ):
            raise ValueError("Rivara Pay webhook order, amount, currency or mode mismatch")
