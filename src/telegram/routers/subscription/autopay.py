from dataclasses import replace
from html import escape
from typing import Any

from adaptix import Retort
from aiogram.types import CallbackQuery, Message
from aiogram_dialog import DialogManager, ShowMode
from aiogram_dialog.widgets.input import MessageInput
from aiogram_dialog.widgets.kbd import Button
from dishka import FromDishka
from dishka.integrations.aiogram_dialog import inject
from loguru import logger

from src.application.common import TranslatorRunner
from src.application.common.dao import PaymentGatewayDao, SubscriptionDao
from src.application.dto import PlanDto, PlanSnapshotDto, PriceDetailsDto, TelegramUserDto
from src.application.dto.payment_gateway import PlategaGatewaySettingsDto
from src.application.services import PricingService
from src.application.use_cases.user.queries.plans import GetAvailablePlans
from src.core.constants import USER_KEY
from src.core.enums import Currency, PaymentGatewayType, PurchaseType
from src.core.utils.i18n_helpers import i18n_format_days
from src.infrastructure.payment_gateways import PlategaGateway
from src.infrastructure.services.platega_autopay import OPEN_STATUSES, PlategaAutopayService
from src.telegram.states import Subscription


async def _prepare(
    manager: DialogManager,
    user: TelegramUserDto,
    plan: PlanDto,
    days: int,
    purchase_type: PurchaseType,
    retort: Retort,
    pricing_service: PricingService,
    autopay: PlategaAutopayService,
) -> None:
    duration = plan.get_duration(days)
    if not duration or plan.is_trial:
        raise ValueError("Autopay is unavailable for this plan")
    PlategaGateway.subscription_interval(days)
    pricing = pricing_service.calculate_for_duration(
        replace(user, purchase_discount=0), duration, Currency.RUB
    )
    if pricing.is_free:
        raise ValueError("Autopay is unavailable for free subscriptions")
    await autopay.gateway(for_creation=True)
    manager.dialog_data.update(
        {
            "ap_plan": retort.dump(PlanSnapshotDto.from_plan(plan, days)),
            "ap_pricing": retort.dump(pricing),
            "ap_purchase_type": purchase_type.value,
        }
    )
    await manager.switch_to(Subscription.AUTOPAY_CONFIRM)


@inject
async def on_autopay_checkout(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    retort: FromDishka[Retort],
    pricing_service: FromDishka[PricingService],
    autopay: FromDishka[PlategaAutopayService],
) -> None:
    user = dialog_manager.middleware_data[USER_KEY]
    try:
        await _prepare(
            dialog_manager,
            user,
            retort.load(dialog_manager.dialog_data[PlanDto.__name__], PlanDto),
            dialog_manager.dialog_data["selected_duration"],
            PurchaseType(dialog_manager.dialog_data["purchase_type"]),
            retort,
            pricing_service,
            autopay,
        )
    except Exception:
        logger.exception("Could not prepare Platega autopay")
        await dialog_manager.switch_to(Subscription.AUTOPAY)


@inject
async def on_autopay_enable(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    retort: FromDishka[Retort],
    subscription_dao: FromDishka[SubscriptionDao],
    available_plans: FromDishka[GetAvailablePlans],
    pricing_service: FromDishka[PricingService],
    autopay: FromDishka[PlategaAutopayService],
    i18n: FromDishka[TranslatorRunner],
) -> None:
    user = dialog_manager.middleware_data[USER_KEY]
    try:
        current = await subscription_dao.get_current(user.id)
        if not current or current.is_trial or current.is_unlimited:
            raise ValueError("No renewable subscription")
        plan = next(
            (p for p in await available_plans.system(user) if p.id == current.plan_snapshot.id),
            None,
        )
        if not plan:
            raise ValueError("Plan is no longer available")
        await _prepare(
            dialog_manager,
            user,
            plan,
            current.plan_snapshot.duration,
            PurchaseType.RENEW,
            retort,
            pricing_service,
            autopay,
        )
    except Exception:
        logger.exception("Could not enable Platega autopay")
        await callback.answer(i18n.get("ntf-autopay-unavailable"), show_alert=True)


@inject
async def autopay_getter(
    dialog_manager: DialogManager,
    user: TelegramUserDto,
    autopay: FromDishka[PlategaAutopayService],
    gateway_dao: FromDishka[PaymentGatewayDao],
    subscription_dao: FromDishka[SubscriptionDao],
    i18n: FromDishka[TranslatorRunner],
    **kwargs: Any,
) -> dict[str, Any]:
    payment = await autopay.current(user.id)
    error = False
    if payment:
        try:
            payment = await autopay.refresh(payment)
        except Exception:
            logger.exception("Could not refresh Platega autopay status")
            error = True
    current = await subscription_dao.get_current(user.id)
    gateway = await gateway_dao.get_by_type(PaymentGatewayType.PLATEGA)
    configured = bool(
        gateway
        and gateway.is_active
        and isinstance(gateway.settings, PlategaGatewaySettingsDto)
        and gateway.settings.is_configured
        and gateway.settings.autopay_enabled
    )
    status = payment.status if payment else "Disabled"
    plan_name = (
        payment.plan_snapshot["name"]
        if payment
        else (current.plan_snapshot.name if current else "—")
    )
    try:
        email = await autopay.email(user)
    except Exception:
        logger.exception("Could not read optional autopay email")
        email = user.billing_email or (payment.email if payment else None) or user.email
    return {
        "ap_status": i18n.get(f"autopay-status-{status.lower()}"),
        "ap_plan_name": escape(i18n.get(plan_name)),
        "ap_next_charge": payment.next_charge_at.strftime("%d.%m.%Y %H:%M UTC")
        if payment and payment.next_charge_at
        else "—",
        "ap_amount": payment.pricing["final_amount"] if payment else "—",
        "ap_email": escape(email) if email else i18n.get("autopay-email-not-set"),
        "ap_has_email": bool(email),
        "ap_error": error,
        "ap_can_cancel": bool(payment and status in OPEN_STATUSES),
        "ap_pending": bool(payment and status == "Pending" and not error),
        "ap_url": payment.payment_url if payment else "",
        "ap_can_enable": bool(
            configured
            and not error
            and status not in OPEN_STATUSES
            and current
            and not current.is_trial
            and not current.is_unlimited
        ),
    }


@inject
async def autopay_confirm_getter(
    dialog_manager: DialogManager,
    retort: FromDishka[Retort],
    i18n: FromDishka[TranslatorRunner],
    **kwargs: Any,
) -> dict[str, Any]:
    plan = retort.load(dialog_manager.dialog_data["ap_plan"], PlanSnapshotDto)
    pricing = retort.load(dialog_manager.dialog_data["ap_pricing"], PriceDetailsDto)
    key, kw = i18n_format_days(plan.duration)
    return {
        "ap_plan_name": escape(i18n.get(plan.name)),
        "ap_amount": pricing.final_amount,
        "ap_period": i18n.get(key, **kw),
    }


@inject
async def on_autopay_email_input(
    message: Message,
    widget: MessageInput,
    dialog_manager: DialogManager,
    autopay: FromDishka[PlategaAutopayService],
    i18n: FromDishka[TranslatorRunner],
) -> None:
    dialog_manager.show_mode = ShowMode.EDIT
    try:
        if not message.text:
            raise ValueError("Missing email")
        await autopay.save_email(dialog_manager.middleware_data[USER_KEY], message.text)
        await dialog_manager.switch_to(Subscription.AUTOPAY)
    except ValueError:
        await message.answer(i18n.get("ntf-autopay-invalid-email"))


@inject
async def on_autopay_create(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    autopay: FromDishka[PlategaAutopayService],
    retort: FromDishka[Retort],
    i18n: FromDishka[TranslatorRunner],
) -> None:
    try:
        await autopay.create(
            dialog_manager.middleware_data[USER_KEY],
            retort.load(dialog_manager.dialog_data["ap_plan"], PlanSnapshotDto),
            retort.load(dialog_manager.dialog_data["ap_pricing"], PriceDetailsDto),
            PurchaseType(dialog_manager.dialog_data["ap_purchase_type"]),
        )
        await dialog_manager.switch_to(Subscription.AUTOPAY)
    except Exception:
        logger.exception("Could not create Platega autopay")
        await callback.answer(i18n.get("ntf-autopay-create-error"), show_alert=True)


@inject
async def on_autopay_cancel(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    autopay: FromDishka[PlategaAutopayService],
    i18n: FromDishka[TranslatorRunner],
) -> None:
    try:
        await autopay.cancel_for_user(dialog_manager.middleware_data[USER_KEY].id)
        await callback.answer(i18n.get("ntf-autopay-cancelled"), show_alert=True)
    except Exception:
        logger.exception("Could not cancel Platega autopay")
        await callback.answer(i18n.get("ntf-autopay-cancel-error"), show_alert=True)
