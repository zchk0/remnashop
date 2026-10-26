from uuid import UUID

from dishka.integrations.taskiq import FromDishka, inject

from src.application.use_cases.gateways.commands.payment import ProcessPayment, ProcessPaymentDto
from src.application.use_cases.misc.commands.maintenance import CancelOldTransactions
from src.core.enums import PaymentGatewayType, TransactionStatus
from src.infrastructure.services.platega_autopay import PlategaAutopayService
from src.infrastructure.taskiq.broker import broker


@broker.task()
@inject(patch_module=True)
async def handle_payment_transaction_task(
    payment_id: UUID,
    payment_status: TransactionStatus,
    gateway_type: PaymentGatewayType,
    process_payment: FromDishka[ProcessPayment],
) -> None:
    await process_payment.system(
        ProcessPaymentDto(
            payment_id=payment_id,
            new_transaction_status=payment_status,
            gateway_type=gateway_type,
        )
    )


@broker.task(schedule=[{"cron": "*/30 * * * *"}])
@inject(patch_module=True)
async def cancel_old_transactions_task(
    cancel_old_transactions: FromDishka[CancelOldTransactions],
) -> None:
    await cancel_old_transactions.system()


@broker.task(retry_on_error=True)
@inject(patch_module=True)
async def handle_platega_autopay_task(
    event_id: str,
    autopay: FromDishka[PlategaAutopayService],
) -> None:
    await autopay.process(event_id)


@broker.task(schedule=[{"cron": "* * * * *"}])
@inject(patch_module=True)
async def retry_platega_autopay_task(
    autopay: FromDishka[PlategaAutopayService],
) -> None:
    for event_id in await autopay.pending_events():
        await handle_platega_autopay_task.kiq(event_id)  # type: ignore[call-overload]
