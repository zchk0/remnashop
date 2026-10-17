from dataclasses import replace
from typing import Any
from urllib.parse import urlparse

from src.application.common import Interactor
from src.application.common.dao import PlanDao, SettingsDao
from src.application.common.dao.earning import EarningDao
from src.application.common.policy import Permission
from src.application.common.uow import UnitOfWork
from src.application.dto import UserDto
from src.application.dto.earning import ChannelTaskDto


class UpdateEarningSettings(Interactor[dict[str, Any], None]):
    required_permission = Permission.MANAGE_EARNING

    def __init__(self, settings_dao: SettingsDao, uow: UnitOfWork) -> None:
        self.settings_dao = settings_dao
        self.uow = uow

    async def _execute(self, actor: UserDto, data: dict[str, Any]) -> None:
        if set(data) - {
            "enabled",
            "audience",
            "allowed_telegram_ids",
            "button_text",
            "button_color",
            "subscriber_price",
        }:
            raise ValueError("Unknown earning setting")
        async with self.uow:
            settings = await self.settings_dao.get()
            updated = replace(settings.earning, **data)
            if updated.audience not in {"all", "admins", "selected"}:
                raise ValueError("Invalid audience")
            if not 1 <= len(updated.button_text.strip()) <= 64:
                raise ValueError("Button text must contain 1–64 characters")
            if not 1 <= len(updated.subscriber_price.strip()) <= 80:
                raise ValueError("Invalid subscriber price")
            if any(value <= 0 for value in updated.allowed_telegram_ids):
                raise ValueError("Invalid Telegram ID")
            settings.earning = updated
            await self.settings_dao.update(settings)
            await self.uow.commit()


class ManageChannelTask(Interactor[ChannelTaskDto, ChannelTaskDto]):
    required_permission = Permission.MANAGE_EARNING

    def __init__(self, earning_dao: EarningDao, plan_dao: PlanDao, uow: UnitOfWork) -> None:
        self.earning_dao = earning_dao
        self.plan_dao = plan_dao
        self.uow = uow

    async def _execute(self, actor: UserDto, task: ChannelTaskDto) -> ChannelTaskDto:
        async with self.uow:
            previous = await self.earning_dao.get_task(task.id, lock=True) if task.id else None
            if task.id and (previous is None or previous.deleted):
                raise ValueError("Task not found")
            if previous and previous.channel_id != task.channel_id and previous.claims_count:
                raise ValueError("Create a new task to change a channel with existing claims")
            self._validate(task)
            for plan_id in (task.plan_id, task.trial_plan_id):
                if plan_id:
                    plan = await self.plan_dao.get_by_id(plan_id)
                    if not plan or plan.is_trial:
                        raise ValueError("Choose a non-trial plan")
            saved = await self.earning_dao.save_task(task)
            await self.uow.commit()
            return saved

    @staticmethod
    def _validate(task: ChannelTaskDto) -> None:
        if not task.title.strip() or len(task.title) > 128:
            raise ValueError("Invalid task title")
        if not 0 <= task.days <= 3650 or not 0 <= task.discount <= 100:
            raise ValueError("Invalid reward")
        if task.max_claims is not None and not 1 <= task.max_claims <= 2147483647:
            raise ValueError("Invalid capacity")
        if task.trial_days is not None and not 1 <= task.trial_days <= 3650:
            raise ValueError("Invalid trial days")
        if task.active:
            url = urlparse(task.channel_url)
            if (
                task.channel_id >= 0
                or url.scheme != "https"
                or url.hostname != "t.me"
                or not url.path.strip("/")
            ):
                raise ValueError("Invalid channel")
            if not (task.days or task.discount or task.reset_traffic):
                raise ValueError("Configure at least one reward")
            if task.trial_plan_id and not task.days:
                raise ValueError("Trial conversion requires a days reward")
