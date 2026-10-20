from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fluent_compiler.bundle import FluentBundle
from fluentogram.translator import FluentTranslator

from src.application.dto import SettingsDto, UserDto
from src.application.events import ReferralRewardFailedEvent, ReferralRewardReceivedEvent
from src.core.constants import CONTAINER_KEY, USER_KEY
from src.core.enums import (
    ReferralAccrualStrategy,
    ReferralLevel,
    ReferralRewardStrategy,
    ReferralRewardType,
    Role,
    SubscriptionStatus,
)
from src.infrastructure.di.providers.retort import RetortProvider
from src.infrastructure.services.translator import TranslatorRunnerImpl
from src.telegram.routers.dashboard.remnashop.referral.dialog import router
from src.telegram.routers.dashboard.remnashop.referral.getters import (
    accrual_strategy_getter,
    level_getter,
    referral_getter,
    reward_getter,
    reward_strategy_getter,
    reward_type_getter,
)
from src.telegram.routers.dashboard.remnashop.referral.handlers import on_invitation_reward_input
from src.telegram.routers.menu.getters import invite_about_getter
from src.telegram.states import RemnashopReferral
from src.web.endpoints.public.referral import get_referral_program


@pytest.fixture(scope="module")
def translator():
    bundle = FluentBundle.from_string(
        locale="ru",
        text="\n".join(
            path.read_text("utf-8") for path in sorted(Path("assets/translations/ru").glob("*.ftl"))
        ),
        use_isolating=False,
    )
    return TranslatorRunnerImpl(
        [FluentTranslator(locale="ru", translator=bundle)], retort=RetortProvider().get_retort()
    )


def settings_for(strategy):
    settings = SettingsDto()
    settings.referral.accrual_strategy = strategy
    settings.referral.invitation_reward = 3
    settings.referral.level = ReferralLevel.SECOND
    settings.referral.reward.config = {ReferralLevel.FIRST: 5, ReferralLevel.SECOND: 1}
    return settings


@pytest.mark.parametrize("strategy", list(ReferralAccrualStrategy))
async def test_admin_windows_render_five_modes_and_separate_reward_settings(translator, strategy):
    settings_dao = SimpleNamespace(get=AsyncMock(return_value=settings_for(strategy)))
    manager = SimpleNamespace(
        dialog_data={},
        is_preview=lambda: False,
        current_context=lambda: SimpleNamespace(widget_data={}),
        middleware_data={
            USER_KEY: UserDto(name="Owner", role=Role.OWNER),
            CONTAINER_KEY: SimpleNamespace(get=AsyncMock(return_value=translator)),
        },
    )
    data = await referral_getter.__dishka_orig_func__(manager, settings_dao, translator)
    data.update(await reward_getter.__dishka_orig_func__(manager, translator, settings_dao))
    for getter in (level_getter, reward_type_getter):
        data.update(await getter(manager))
    for window in router.windows.values():
        window_data = data.copy()
        if window.state == RemnashopReferral.ACCRUAL_STRATEGY:
            window_data.update(await accrual_strategy_getter(manager))
        elif window.state == RemnashopReferral.REWARD_STRATEGY:
            window_data.update(await reward_strategy_getter(manager))
        text = await window.render_text(window_data, manager)
        assert text and len(text) < 4096
        keyboard = await window.keyboard.render_keyboard(window_data, manager)
        assert keyboard
        assert all(not button.text.startswith("btn-") for row in keyboard for button in row)
        if window.state == RemnashopReferral.MAIN:
            labels = [button.text for row in keyboard for button in row]
            assert ("👥 Награда за приглашение" in labels) == strategy.rewards_invitation
            assert ("🎁 Награда за платежи" in labels) == strategy.rewards_payments
        if window.state == RemnashopReferral.ACCRUAL_STRATEGY:
            assert len(keyboard) == 6  # Five choices and Back.


@pytest.mark.parametrize("strategy", list(ReferralAccrualStrategy))
async def test_user_sees_only_enabled_rewards_and_independent_invitation_amount(
    translator, strategy
):
    data = await invite_about_getter.__dishka_orig_func__(
        dialog_manager=SimpleNamespace(),
        i18n=translator,
        settings_dao=SimpleNamespace(get=AsyncMock(return_value=settings_for(strategy))),
    )
    text = translator.get("msg-menu-invite-about", **data)
    assert ("За приглашение: 3 доп. дня" in text) == strategy.rewards_invitation
    assert ("За ваших друзей: 5 доп. дней" in text) == strategy.rewards_payments
    assert ("За приглашенных вашими друзьями: 1 доп. день" in text) == strategy.rewards_payments


async def test_invitation_is_shown_as_fixed_amount_when_payment_reward_is_percentage(translator):
    settings = settings_for(ReferralAccrualStrategy.ON_EACH_PAYMENT_AND_INVITATION)
    settings.referral.reward.strategy = ReferralRewardStrategy.PERCENT
    data = await invite_about_getter.__dishka_orig_func__(
        dialog_manager=SimpleNamespace(),
        i18n=translator,
        settings_dao=SimpleNamespace(get=AsyncMock(return_value=settings)),
    )
    text = translator.get("msg-menu-invite-about", **data)
    assert "За приглашение: 3 доп. дня" in text
    assert "5% доп. дней" in text


@pytest.mark.parametrize("is_invitation", [True, False])
@pytest.mark.parametrize("event_type", [ReferralRewardReceivedEvent, ReferralRewardFailedEvent])
def test_notifications_describe_the_actual_reason_for_reward(translator, is_invitation, event_type):
    event = event_type(
        user=UserDto(name="Referrer"),
        name="Friend",
        value=3,
        reward_type=ReferralRewardType.EXTRA_DAYS,
        is_invitation=is_invitation,
    )
    payload = event.as_payload()
    text = translator.get(payload.i18n_key, **payload.i18n_kwargs)
    assert ("зарегистрировался по вашей ссылке" in text) == is_invitation
    assert ("совершил платеж" in text) != is_invitation


@pytest.mark.parametrize("key", ["event-referral.reward", "event-referral.reward-failed"])
def test_queued_payment_notification_still_renders_without_invitation_flag(translator, key):
    text = translator.get(key, name="Friend", value=5, reward_type=ReferralRewardType.EXTRA_DAYS)
    assert "совершил платеж" in text


async def test_invalid_invitation_input_keeps_settings_and_shows_validation_message():
    user = UserDto(name="Owner", role=Role.OWNER)
    update = AsyncMock(side_effect=ValueError("Invalid amount"))
    notifier = SimpleNamespace(notify_user=AsyncMock())
    manager = SimpleNamespace(middleware_data={USER_KEY: user})
    await on_invitation_reward_input.__dishka_orig_func__(
        SimpleNamespace(text="not a number"), None, manager, notifier, update
    )
    notifier.notify_user.assert_awaited_once_with(user, i18n_key="ntf-common.invalid-value")


@pytest.mark.parametrize("strategy", list(ReferralAccrualStrategy))
async def test_public_api_exposes_invitation_reward_separately_from_payment_levels(strategy):
    result = await get_referral_program.__dishka_orig_func__(
        user=UserDto(id=1, name="User", referral_code="ref", is_email_verified=True),
        settings_dao=SimpleNamespace(get=AsyncMock(return_value=settings_for(strategy))),
        referral_dao=SimpleNamespace(
            get_referrals_count=AsyncMock(return_value=2),
            get_referrals_with_payment_count=AsyncMock(return_value=1),
        ),
        subscription_dao=SimpleNamespace(
            get_current=AsyncMock(
                return_value=SimpleNamespace(current_status=SubscriptionStatus.ACTIVE)
            )
        ),
    )
    assert result.invitation_reward == (3 if strategy.rewards_invitation else None)
    assert [level.value for level in result.reward_levels] == (
        [5, 1] if strategy.rewards_payments else []
    )
