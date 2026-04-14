import re

from aiogram import F, Router
from aiogram.filters import CommandObject, CommandStart
from aiogram.types import CallbackQuery, Message
from aiogram_dialog import DialogManager, ShowMode, StartMode
from dishka import FromDishka
from dishka.integrations.aiogram_dialog import inject
from loguru import logger

from src.application.common import Notifier
from src.application.common.dao import PaymentGatewayDao, SubscriptionDao
from src.application.dto import PlanPriceDto, UserDto
from src.application.use_cases.plan.queries.match import MatchPlan, MatchPlanDto
from src.application.use_cases.user.queries.plans import GetAvailablePlanByCode, GetAvailablePlans
from src.core.constants import GOTO_PREFIX, PAYMENT_PREFIX, TARGET_TELEGRAM_ID
from src.core.enums import Currency, Deeplink, PurchaseType
from src.telegram.states import DashboardUser, MainMenu, Subscription, state_from_string

router = Router(name=__name__)
BUY_DEEPLINK_RE = re.compile(rf"^{Deeplink.BUY.with_underscore}(?P<plan_id>\d+)_(?P<days>\d+)$")


def _parse_buy_deeplink(args: str) -> tuple[int, int] | None:
    match = BUY_DEEPLINK_RE.fullmatch(args)
    if not match:
        return None

    return int(match.group("plan_id")), int(match.group("days"))


def _has_gateway_price(duration_prices: list[PlanPriceDto], gateway_currency: Currency) -> bool:
    return any(price.currency == gateway_currency for price in duration_prices)


@router.callback_query(F.data.startswith(GOTO_PREFIX))
async def on_goto(callback: CallbackQuery, dialog_manager: DialogManager, user: UserDto) -> None:
    logger.info(f"{user.log} Try go to '{callback.data}'")
    data = callback.data.removeprefix(GOTO_PREFIX)  # type: ignore[union-attr]

    if data.startswith(PAYMENT_PREFIX):
        # TODO: Implement a transition to a specific type of payment
        # There shit with data...
        await dialog_manager.bg(
            user_id=user.telegram_id,
            chat_id=user.telegram_id,
        ).start(
            state=Subscription.MAIN,
            mode=StartMode.RESET_STACK,
            show_mode=ShowMode.DELETE_AND_SEND,
        )
        await callback.answer()
        return

    state = state_from_string(data)

    if not state:
        logger.warning(f"{user.log} Trying go to not exist state '{data}'")
        await callback.answer()
        return

    if state == DashboardUser.MAIN:
        parts = data.split(":")

        try:
            target_telegram_id = int(parts[2])
        except ValueError:
            logger.warning(f"{user.log} Invalid target_telegram_id in callback: {parts[2]}")

        await dialog_manager.bg(
            user_id=user.telegram_id,
            chat_id=user.telegram_id,
        ).start(
            state=DashboardUser.MAIN,
            data={TARGET_TELEGRAM_ID: target_telegram_id},
            mode=StartMode.RESET_STACK,
            show_mode=ShowMode.DELETE_AND_SEND,
        )
        logger.debug(f"{user.log} Redirected to user '{target_telegram_id}'")
        await callback.answer()
        return

    logger.debug(f"{user.log} Redirected to '{state}'")
    await dialog_manager.bg(
        user_id=user.telegram_id,
        chat_id=user.telegram_id,
    ).start(
        state=state,
        mode=StartMode.RESET_STACK,
        show_mode=ShowMode.DELETE_AND_SEND,
    )
    await callback.answer()


@inject
@router.message(
    CommandStart(deep_link=True, ignore_case=True),
    F.text.contains(Deeplink.BUY.with_underscore),
)
async def on_goto_buy(
    message: Message,
    command: CommandObject,
    dialog_manager: DialogManager,
    user: UserDto,
    get_available_plans: FromDishka[GetAvailablePlans],
    subscription_dao: FromDishka[SubscriptionDao],
    payment_gateway_dao: FromDishka[PaymentGatewayDao],
    match_plan: FromDishka[MatchPlan],
    notifier: FromDishka[Notifier],
) -> None:
    args = command.args or ""
    parsed = _parse_buy_deeplink(args)

    if not parsed:
        logger.warning(f"{user.log} Invalid ToBeVPN buy deeplink payload '{args}'")
        await notifier.notify_user(user=user, i18n_key="ntf-common.plan-not-found")
        return

    plan_id, duration_days = parsed
    plans = await get_available_plans.system(user)
    plan = next((p for p in plans if p.id == plan_id), None)

    if not plan:
        logger.warning(f"{user.log} ToBeVPN buy plan '{plan_id}' not found or unavailable")
        await notifier.notify_user(user=user, i18n_key="ntf-common.plan-not-found")
        return

    duration = plan.get_duration(duration_days)

    if not duration:
        logger.warning(
            f"{user.log} ToBeVPN buy duration '{duration_days}' not found "
            f"for plan '{plan_id}'"
        )
        await notifier.notify_user(user=user, i18n_key="ntf-common.plan-not-found")
        return

    gateways = await payment_gateway_dao.get_active()
    available_gateways = [
        gateway for gateway in gateways if _has_gateway_price(duration.prices, gateway.currency)
    ]

    if not available_gateways:
        logger.warning(
            f"{user.log} No active payment gateways with price for "
            f"ToBeVPN plan '{plan_id}' and duration '{duration_days}'"
        )
        await notifier.notify_user(user=user, i18n_key="ntf-subscription.gateways-unavailable")
        return

    current_subscription = await subscription_dao.get_current(user.telegram_id)
    purchase_type = PurchaseType.NEW

    if current_subscription:
        matched_plan = await match_plan.system(
            MatchPlanDto(plan_snapshot=current_subscription.plan_snapshot, plans=[plan])
        )
        if matched_plan and not current_subscription.is_unlimited:
            purchase_type = PurchaseType.RENEW
        else:
            purchase_type = PurchaseType.CHANGE

    logger.info(
        f"{user.log} Redirected to ToBeVPN buy plan '{plan_id}' "
        f"for '{duration_days}' days"
    )

    await dialog_manager.bg(
        user_id=user.telegram_id,
        chat_id=user.telegram_id,
    ).start(
        state=Subscription.PAYMENT_METHOD,
        data={
            "plan_id": plan.id,
            "selected_duration": duration.days,
            "purchase_type": purchase_type,
            "only_single_plan": True,
            "only_single_duration": True,
        },
        mode=StartMode.RESET_STACK,
        show_mode=ShowMode.DELETE_AND_SEND,
    )


@inject
@router.message(CommandStart(deep_link=True, ignore_case=True), F.text.contains(Deeplink.PLAN))
async def on_goto_plan(
    message: Message,
    command: CommandObject,
    dialog_manager: DialogManager,
    user: UserDto,
    get_available_plan_by_code: FromDishka[GetAvailablePlanByCode],
    notifier: FromDishka[Notifier],
) -> None:
    args = command.args or ""
    public_code = args.removeprefix(Deeplink.PLAN.with_underscore)
    plan = await get_available_plan_by_code(user, public_code)

    # TODO: Handle brootforce of plan codes

    if not plan:
        logger.warning(f"{user.log} Plan with code '{public_code}' not found or not available")
        await notifier.notify_user(user=user, i18n_key="ntf-common.plan-not-found")
        return

    logger.info(f"{user.log} Redirected to plan '{public_code}'")

    await dialog_manager.bg(
        user_id=user.telegram_id,
        chat_id=user.telegram_id,
    ).start(
        state=Subscription.PLAN,
        data={"plan_id": plan.id},
        mode=StartMode.RESET_STACK,
        show_mode=ShowMode.DELETE_AND_SEND,
    )


@router.message(CommandStart(deep_link=True, ignore_case=True), F.text.contains(Deeplink.INVITE))
async def on_goto_invite(
    message: Message,
    command: CommandObject,
    user: UserDto,
    dialog_manager: DialogManager,
) -> None:
    if command.args == Deeplink.INVITE:
        logger.info(f"{user.log} Redirected to invite menu")
        await dialog_manager.start(
            state=MainMenu.INVITE,
            mode=StartMode.RESET_STACK,
            show_mode=ShowMode.DELETE_AND_SEND,
        )
