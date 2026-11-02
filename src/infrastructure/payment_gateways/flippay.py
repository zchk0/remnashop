import hashlib
import hmac
import re
from decimal import Decimal, InvalidOperation
from typing import Any, Final
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import orjson
from aiogram import Bot
from fastapi import Request

from src.application.dto import PaymentGatewayDto, PaymentResultDto, TransactionDto
from src.application.dto.payment_gateway import FlippayGatewaySettingsDto
from src.core.config import AppConfig
from src.core.enums import Currency, PaymentGatewayType, TransactionStatus

from .base import BasePaymentGateway


class FlippayGateway(BasePaymentGateway):
    """FlipPay merchant API: https://flippay.pro/docs."""

    API_BASE: Final[str] = "https://flippay.pro/api/v1/"
    PAYMENT_STATUSES: Final[dict[str, TransactionStatus]] = {
        "success": TransactionStatus.COMPLETED,
        "failed": TransactionStatus.FAILED,
        "refunded": TransactionStatus.REFUNDED,
    }

    def __init__(self, gateway: PaymentGatewayDto, bot: Bot, config: AppConfig) -> None:
        super().__init__(gateway, bot, config)
        if not isinstance(gateway.settings, FlippayGatewaySettingsDto):
            raise TypeError("Invalid FlipPay settings")
        if not gateway.settings.is_configured or gateway.currency != Currency.RUB:
            raise ValueError("FlipPay requires configured credentials, method and RUB currency")
        self.settings = gateway.settings
        assert self.settings.api_key is not None and self.settings.api_secret is not None
        assert self.settings.webhook_secret is not None
        self._webhook_secret = self.settings.webhook_secret.get_secret_value().encode()
        self._client = self._make_client(
            base_url=self.API_BASE,
            headers={
                "X-Api-Key": self.settings.api_key.get_secret_value(),
                "X-Api-Secret": self.settings.api_secret.get_secret_value(),
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )

    @staticmethod
    def _amount(value: Any) -> Decimal:
        try:
            amount = Decimal(str(value))
            if not amount.is_finite() or amount <= 0 or amount != amount.quantize(Decimal("0.01")):
                raise ValueError("Invalid FlipPay amount")
        except InvalidOperation as error:
            raise ValueError("Invalid FlipPay amount") from error
        return amount

    async def handle_create_payment(self, amount: Decimal, details: str) -> PaymentResultDto:
        amount = self._amount(amount)
        order_id = uuid4()
        redirect_url = await self._get_bot_redirect_url()
        response = await self._client.post(
            "payments",
            json={
                "order_id": str(order_id),
                "amount": format(amount, ".2f"),
                "currency": Currency.RUB.value,
                "payment_method": self.settings.payment_method,
                "description": details,
                "success_url": redirect_url,
                "fail_url": redirect_url,
            },
        )
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict) or UUID(str(data.get("order_id"))) != order_id:
            raise ValueError("FlipPay creation response order ID mismatch")
        payment_url = data.get("pay_url")
        if not isinstance(payment_url, str):
            raise ValueError("FlipPay creation response is missing pay_url")
        parsed_url = urlsplit(payment_url)
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.hostname:
            raise ValueError("Invalid FlipPay payment URL")
        # The payment page may use a different domain from the merchant API.
        return PaymentResultDto(id=order_id, url=payment_url)

    async def get_payment(self, payment_id: UUID) -> dict[str, Any]:
        response = await self._client.get(f"payments/{payment_id}")
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("Invalid FlipPay transaction response")
        return data

    async def handle_webhook(self, request: Request) -> tuple[UUID, TransactionStatus] | None:
        raw_body = await request.body()
        signature = request.headers.get("X-Signature", "")
        expected = hmac.new(self._webhook_secret, raw_body, hashlib.sha256).hexdigest()
        if not re.fullmatch(r"[0-9a-fA-F]{64}", signature) or not hmac.compare_digest(
            expected, signature.lower()
        ):
            raise PermissionError("Invalid FlipPay webhook signature")
        data = orjson.loads(raw_body)
        if not isinstance(data, dict) or data.get("event") != "payment.updated":
            raise ValueError("Invalid FlipPay webhook event")
        payment_id = UUID(str(data.get("order_id")))
        self._amount(data.get("amount"))
        if data.get("currency") != Currency.RUB.value:
            raise ValueError("Invalid FlipPay webhook currency")
        status = data.get("status")
        payment_status = self.PAYMENT_STATUSES.get(status) if isinstance(status, str) else None
        if payment_status is None:
            raise ValueError("Unsupported FlipPay payment status")
        return payment_id, payment_status

    @classmethod
    def validate_payment_data(cls, data: dict[str, Any], transaction: TransactionDto) -> None:
        """Compare merchant amount, excluding customer fees, with the saved order."""
        if (
            transaction.gateway_type != PaymentGatewayType.FLIPPAY
            or transaction.currency != Currency.RUB
            or UUID(str(data.get("order_id"))) != transaction.payment_id
            or data.get("currency") != transaction.currency.value
            or cls._amount(data.get("amount")) != transaction.pricing.final_amount
        ):
            raise ValueError("FlipPay transaction ID, gateway, amount or currency mismatch")

    async def validate_webhook_transaction(
        self, request: Request, transaction: TransactionDto
    ) -> None:
        # Request bodies belong to the request; gateway instances are shared between requests.
        self.validate_payment_data(orjson.loads(await request.body()), transaction)
