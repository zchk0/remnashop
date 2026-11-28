import asyncio
import secrets
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from dishka import FromDishka
from dishka.integrations.fastapi import inject
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from httpx import HTTPError, HTTPStatusError
from loguru import logger
from pydantic import AwareDatetime, BaseModel

from src.application.common.dao import TransactionDao
from src.application.common.uow import UnitOfWork
from src.application.use_cases.gateways.queries.providers import GetPaymentGatewayInstance
from src.core.config import AppConfig
from src.core.constants import API_V1
from src.core.enums import Currency, PaymentGatewayType
from src.core.exceptions import GatewayNotConfiguredError
from src.infrastructure.payment_gateways.valutix import ValutixGateway

router = APIRouter(prefix=API_V1 + "/reports", include_in_schema=False)

PAGE_SIZE = 24
CONCURRENT_LOOKUPS = 6
CHECKOUT_DATE_BUFFER = timedelta(hours=1)


class ValutixReportPage(BaseModel):
    total_received_rub: Decimal
    completed_payments: int
    next_cursor: int | None


@inject
async def require_report_token(
    config: FromDishka[AppConfig],
    token: Annotated[str, Header(alias="X-Valutix-Report-Token")] = "",
) -> None:
    expected = config.valutix_report_token
    if not expected or not secrets.compare_digest(
        token.encode(), expected.get_secret_value().encode()
    ):
        raise HTTPException(status_code=401, detail="Invalid Valutix report token")


async def _sum_orders(
    gateway: ValutixGateway,
    order_ids: list[UUID],
    from_date: datetime,
    until_date: datetime,
) -> tuple[Decimal, int]:
    total_received = Decimal(0)
    completed_payments = 0
    rub = Currency.RUB.value
    for start in range(0, len(order_ids), CONCURRENT_LOOKUPS):
        batch = order_ids[start : start + CONCURRENT_LOOKUPS]
        orders = await asyncio.gather(
            *(gateway.get_order(order_id) for order_id in batch), return_exceptions=True
        )
        for order in orders:
            if isinstance(order, BaseException):
                raise order
            if (
                order.status != "COMPLETED"
                or order.is_test
                or order.currency != rub
                or not from_date <= order.created_at < until_date
            ):
                continue
            if order.settlement_currency not in (None, rub):
                raise HTTPException(
                    status_code=502, detail="Valutix order settled in another currency"
                )
            if order.received is None:
                raise HTTPException(
                    status_code=502, detail="Completed Valutix order has no received amount"
                )
            total_received += order.received
            completed_payments += 1
    return total_received, completed_payments


@router.get("/valutix", dependencies=[Depends(require_report_token)])
@inject
async def get_valutix_report(
    response: Response,
    from_date: AwareDatetime,
    until_date: AwareDatetime,
    gateway_provider: FromDishka[GetPaymentGatewayInstance],
    transaction_dao: FromDishka[TransactionDao],
    uow: FromDishka[UnitOfWork],
    cursor: Annotated[int, Query(ge=0, le=2**31 - 1)] = 0,
) -> ValutixReportPage:
    if not timedelta(0) < until_date - from_date <= timedelta(days=31):
        raise HTTPException(status_code=422, detail="Invalid Valutix report period")

    async with uow:
        try:
            gateway = await gateway_provider.for_webhook(PaymentGatewayType.VALUTIX)
        except GatewayNotConfiguredError:
            raise HTTPException(
                status_code=503, detail="Valutix is not configured in Remnashop"
            ) from None
        if not isinstance(gateway, ValutixGateway):
            raise HTTPException(status_code=503, detail="Valutix is not configured in Remnashop")
        # Use the provider's createdAt for the report, including checkouts straddling midnight.
        candidates = await transaction_dao.list_valutix_order_ids(
            from_date - CHECKOUT_DATE_BUFFER,
            until_date + CHECKOUT_DATE_BUFFER,
            cursor,
            PAGE_SIZE + 1,
        )
        await uow.commit()

    try:
        async with asyncio.timeout(24):
            total_received, completed_payments = await _sum_orders(
                gateway, [order_id for _, order_id in candidates[:PAGE_SIZE]], from_date, until_date
            )
    except HTTPStatusError as error:
        upstream_status = error.response.status_code
        logger.warning("Valutix report lookup returned HTTP {}", upstream_status)
        raise HTTPException(
            status_code=502, detail=f"Valutix API returned HTTP {upstream_status}"
        ) from None
    except (HTTPError, TimeoutError, ValueError) as error:
        logger.warning("Valutix report lookup failed ({})", type(error).__name__)
        raise HTTPException(
            status_code=502, detail="Valutix order data is unavailable or invalid"
        ) from None

    response.headers["Cache-Control"] = "private, no-store"
    return ValutixReportPage(
        total_received_rub=total_received,
        completed_payments=completed_payments,
        next_cursor=candidates[PAGE_SIZE - 1][0] if len(candidates) > PAGE_SIZE else None,
    )
