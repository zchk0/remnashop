from html import escape
from typing import Any

from aiogram_dialog import DialogManager
from dishka import FromDishka
from dishka.integrations.aiogram_dialog import inject

from src.application.common import TranslatorRunner
from src.application.common.dao import PlanDao, SettingsDao
from src.application.common.dao.earning import EarningDao
from src.application.dto.earning import ChannelTaskDto
from src.telegram.routers.earning.getters import reward_text

from .handlers import admin_actor


@inject
async def admin_getter(
    dialog_manager: DialogManager,
    earning_dao: FromDishka[EarningDao],
    settings_dao: FromDishka[SettingsDao],
    plan_dao: FromDishka[PlanDao],
    i18n: FromDishka[TranslatorRunner],
    **kwargs: Any,
) -> dict[str, Any]:
    admin_actor(dialog_manager)
    settings = (await settings_dao.get()).earning
    tasks = await earning_dao.list_tasks()
    plans = [plan for plan in await plan_dao.get_all() if not plan.is_trial]
    names = {plan.id: plan.name for plan in plans}
    task = ChannelTaskDto(**dialog_manager.dialog_data.get("task", {}))
    claims = await earning_dao.get_pending_claims()
    selected_claim = next(
        (
            claim
            for claim in claims
            if (
                claim.task_id == dialog_manager.dialog_data.get("claim_task_id")
                and claim.user_id == dialog_manager.dialog_data.get("claim_user_id")
            )
        ),
        None,
    )
    yes = i18n.get("earning-yes")
    no = i18n.get("earning-no")
    unset = i18n.get("earning-unset")
    payload = selected_claim.payload if selected_claim else {}
    target = payload.get("subscription", {})
    return {
        "pending_claims": [
            {
                "id": f"{claim.task_id}.{claim.user_id}",
                "label": f"👤 {claim.user_id} · #{claim.task_id}",
            }
            for claim in claims
        ],
        "claim_found": selected_claim is not None,
        "claim_user_id": selected_claim.user_id if selected_claim else "—",
        "claim_task_id": selected_claim.task_id if selected_claim else "—",
        "claim_days": payload.get("days", 0),
        "claim_discount": payload.get("discount", 0),
        "claim_reset": yes if payload.get("reset_traffic") else no,
        "claim_expire": escape(str(target.get("expire_at", "—"))),
        "claim_panel_id": target.get("panel_user_id") or target.get("user_remna_id") or "—",
        "claim_subscription_done": yes
        if selected_claim and selected_claim.subscription_applied
        else no,
        "reset_uncertain": bool(
            selected_claim and selected_claim.reset_started and not selected_claim.reset_applied
        ),
        "enabled_label": yes if settings.enabled else no,
        "audience_label": i18n.get(f"earning-audience-{settings.audience}"),
        "selected_ids": escape(", ".join(map(str, settings.allowed_telegram_ids)) or "—"),
        "button_text": escape(settings.button_text),
        "price": escape(settings.subscriber_price),
        "tasks": [
            {
                "id": item.id,
                "label": f"{'🟢' if item.active else '⚪'} {item.title}"
                f" · {item.claims_count}/{item.max_claims or '∞'}",
            }
            for item in tasks
        ],
        "title": escape(task.title),
        "channel_id": task.channel_id or unset,
        "channel_url": escape(task.channel_url or unset),
        "active_label": yes if task.active else no,
        "reward": reward_text(task, None, i18n) or unset,
        "reset_label": yes if task.reset_traffic else no,
        "max_claims": task.max_claims or "∞",
        "claims_count": task.claims_count,
        "plan_name": escape(names.get(task.plan_id or 0, unset)),
        "trial_plan_name": escape(names.get(task.trial_plan_id or 0, unset)),
        "trial_days": task.trial_days or task.days,
        "saved_task": task.id != 0,
        "input_key": "msg-earning-input-"
        + dialog_manager.dialog_data.get("input_field", "title").replace("_", "-"),
        "plans": [
            {"id": 0, "name": unset},
            *[{"id": plan.id, "name": plan.name} for plan in plans],
        ],
    }
