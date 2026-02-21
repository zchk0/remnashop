from uuid import UUID

from dishka.integrations.taskiq import FromDishka, inject

from src.application.use_cases.payment_gateway import ProcessPayment, ProcessPaymentDto
from src.application.use_cases.transaction import CancelOldTransactions
from src.core.enums import TransactionStatus
from src.infrastructure.taskiq.broker import broker


@broker.task()
@inject
async def handle_payment_transaction_task(
    payment_id: UUID,
    payment_status: TransactionStatus,
    process_payment: FromDishka[ProcessPayment],
) -> None:
    await process_payment.system(ProcessPaymentDto(payment_id, payment_status))


@broker.task(schedule=[{"cron": "*/30 * * * *"}])
@inject
async def cancel_old_transactions_task(
    cancel_old_transactions: FromDishka[CancelOldTransactions],
) -> None:
    await cancel_old_transactions.system()
