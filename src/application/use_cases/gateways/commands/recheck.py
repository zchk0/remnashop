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
from src.infrastructure.payment_gateways import PlategaGateway


def can_recheck_payment(transaction: TransactionDto) -> bool:
    return (
        transaction.gateway_type == PaymentGatewayType.PLATEGA
        and not transaction.is_test
        and not transaction.pricing.is_free
        and transaction.payment_method != "6"
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
        gateway = await self.get_payment_gateway_instance.for_webhook(PaymentGatewayType.PLATEGA)
        if not isinstance(gateway, PlategaGateway):
            raise ValueError("Expected a Platega gateway")

        payment = await gateway.get_payment(payment_id)
        if UUID(str(payment.get("id"))) != payment_id:
            raise ValueError("Platega transaction ID mismatch")
        status = payment.get("status")
        if not isinstance(status, str) or not status.strip():
            raise ValueError("Platega transaction status is missing")
        status = status.strip().upper()

        logger.info(f"Payment recheck '{payment_id}' by {actor.log}: Platega status '{status}'")
        if status != "CONFIRMED":
            return RecheckPaymentResultDto(provider_status=status)

        _validate_confirmed_payment(payment, transaction)
        try:
            processed = await self.process_payment.system(
                ProcessPaymentDto(
                    payment_id=payment_id,
                    new_transaction_status=TransactionStatus.COMPLETED,
                    gateway_type=PaymentGatewayType.PLATEGA,
                    recover_canceled=True,
                )
            )
        except PurchaseError:
            raise
        except Exception as error:
            logger.warning(f"Payment recovery '{payment_id}' failed: {error}")
            raise PurchaseError(error) from error
        return RecheckPaymentResultDto(provider_status=status, processed=processed)
