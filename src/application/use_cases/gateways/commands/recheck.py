from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from loguru import logger

from src.application.common import Interactor
from src.application.common.dao import TransactionDao
from src.application.common.policy import Permission
from src.application.dto import TransactionDto, UserDto
from src.application.use_cases.gateways.commands.payment import ProcessPayment, ProcessPaymentDto
from src.application.use_cases.gateways.queries.providers import GetPaymentGatewayInstance
from src.core.enums import PaymentGatewayType, TransactionStatus
from src.core.exceptions import PurchaseError
from src.infrastructure.payment_gateways import FlippayGateway, PlategaGateway, RivaraGateway


def can_recheck_payment(transaction: TransactionDto) -> bool:
    return (
        transaction.gateway_type
        in {PaymentGatewayType.PLATEGA, PaymentGatewayType.FLIPPAY, PaymentGatewayType.RIVARAPAY}
        and not transaction.is_test
        and not transaction.pricing.is_free
        and not (
            transaction.gateway_type == PaymentGatewayType.PLATEGA
            and transaction.payment_method == "6"
        )
    )


def _validate_confirmed_payment(payment: dict[str, Any], transaction: TransactionDto) -> None:
    details = payment.get("paymentDetails")
    if not isinstance(details, dict) or payment.get("subscriptionId"):
        raise ValueError("Invalid Platega payment details for an ordinary transaction")
    try:
        amount = Decimal(str(details.get("amount")))
    except InvalidOperation as error:
        raise ValueError("Invalid Platega transaction amount") from error
    if (
        not amount.is_finite()
        or amount != transaction.pricing.final_amount
        or details.get("currency") != transaction.currency.value
    ):
        raise ValueError("Platega transaction amount/currency mismatch")


@dataclass(frozen=True)
class RecheckPaymentResultDto:
    provider_status: str
    processed: bool = False
    is_paid: bool = False


async def _get_payment_status(
    gateway: PlategaGateway | FlippayGateway | RivaraGateway, transaction: TransactionDto
) -> tuple[str, bool]:
    if isinstance(gateway, RivaraGateway):
        if transaction.provider_payment_id is None:
            raise ValueError("Rivara Pay provider payment ID is missing")
        payment = await gateway.get_payment(transaction.provider_payment_id)
        gateway.validate_payment_data(payment, transaction)
        status = payment.get("status")
        if not isinstance(status, str) or not status.strip():
            raise ValueError("Rivara Pay payment status is missing")
        return status, status == "SUCCEEDED"
    payment = await gateway.get_payment(transaction.payment_id)
    is_flippay = isinstance(gateway, FlippayGateway)
    id_field = "order_id" if is_flippay else "id"
    if UUID(str(payment.get(id_field))) != transaction.payment_id:
        raise ValueError("Payment recheck transaction ID mismatch")
    status = payment.get("status")
    if not isinstance(status, str) or not status.strip():
        raise ValueError("Payment recheck transaction status is missing")
    status = status.strip().upper()
    is_paid = status == ("SUCCESS" if is_flippay else "CONFIRMED")
    if is_paid:
        if is_flippay:
            FlippayGateway.validate_payment_data(payment, transaction)
        else:
            _validate_confirmed_payment(payment, transaction)
    return status, is_paid


class RecheckPayment(Interactor[UUID, RecheckPaymentResultDto]):
    required_permission = Permission.USER_SUBSCRIPTION_EDITOR

    def __init__(
        self,
        transaction_dao: TransactionDao,
        get_payment_gateway_instance: GetPaymentGatewayInstance,
        process_payment: ProcessPayment,
    ) -> None:
        self.transaction_dao = transaction_dao
        self.get_payment_gateway_instance = get_payment_gateway_instance
        self.process_payment = process_payment

    async def _execute(self, actor: UserDto, payment_id: UUID) -> RecheckPaymentResultDto:
        transaction = await self.transaction_dao.get_by_payment_id(payment_id)
        if transaction is None or not can_recheck_payment(transaction):
            raise ValueError("Transaction is not available for payment recheck")

        # Disabling new payments must not prevent recovery of an existing paid order.
        gateway = await self.get_payment_gateway_instance.for_webhook(transaction.gateway_type)
        if not isinstance(gateway, (PlategaGateway, FlippayGateway, RivaraGateway)):
            raise ValueError("Gateway does not support payment recheck")

        status, is_paid = await _get_payment_status(gateway, transaction)
        logger.info(
            f"Payment recheck '{payment_id}' by {actor.log}: "
            f"{transaction.gateway_type} status '{status}'"
        )
        if not is_paid:
            return RecheckPaymentResultDto(provider_status=status)

        try:
            processed = await self.process_payment.system(
                ProcessPaymentDto(
                    payment_id=payment_id,
                    new_transaction_status=TransactionStatus.COMPLETED,
                    gateway_type=transaction.gateway_type,
                    recover_canceled=True,
                )
            )
        except PurchaseError:
            raise
        except Exception as error:
            logger.warning(f"Payment recovery '{payment_id}' failed: {error}")
            raise PurchaseError(error) from error
        return RecheckPaymentResultDto(provider_status=status, processed=processed, is_paid=True)
