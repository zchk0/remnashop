from typing import Optional

from src.application.dto import BroadcastDto
from src.infrastructure.taskiq.tasks.notifications import notify_payments_restored


class PaymentNotificationDispatcherImpl:
    async def notify_payments_restored(self, user_ids: list[int]) -> None:
        await notify_payments_restored.kiq(user_ids)  # type: ignore[call-overload]


class BroadcastDispatcherImpl:
    async def start(
        self,
        broadcast: BroadcastDto,
        plan_id: Optional[int],
        excluded_telegram_ids: list[int],
        exclude_registered_older_than_days: Optional[int],
    ) -> None:
        from src.infrastructure.taskiq.tasks.broadcast import send_broadcast_task  # noqa: PLC0415

        await (
            send_broadcast_task.kicker()
            .with_task_id(str(broadcast.task_id))
            .kiq(
                broadcast,
                plan_id,
                excluded_telegram_ids,
                exclude_registered_older_than_days,
            )  # type: ignore[call-overload]
        )

    async def delete(self, broadcast: BroadcastDto) -> None:
        from src.infrastructure.taskiq.tasks.broadcast import delete_broadcast_task  # noqa: PLC0415

        await delete_broadcast_task.kiq(broadcast)  # type: ignore[call-overload]
