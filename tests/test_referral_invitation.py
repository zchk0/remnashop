from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from remnapy.enums import TrafficLimitStrategy

from src.application.dto import (
    PlanSnapshotDto,
    PriceDetailsDto,
    ReferralDto,
    SettingsDto,
    SubscriptionDto,
    TransactionDto,
    UserDto,
)
from src.application.events import ReferralRewardFailedEvent, ReferralRewardReceivedEvent
from src.application.use_cases.referral.commands.attachment import AttachReferral, AttachReferralDto
from src.application.use_cases.referral.commands.rewards import (
    AssignReferralRewards,
    AssignReferralRewardsDto,
    GiveReferrerReward,
)
from src.application.use_cases.referral.queries.calculations import CalculateReferralReward
from src.application.use_cases.settings.commands.referral import UpdateReferralInvitationReward
from src.application.use_cases.subscription.commands.management import AddSubscriptionDuration
from src.core.enums import (
    Currency,
    PaymentGatewayType,
    PurchaseType,
    ReferralAccrualStrategy,
    ReferralLevel,
    ReferralRewardStrategy,
    ReferralRewardType,
    Role,
    TransactionStatus,
)
from src.core.exceptions import PermissionDeniedError
from src.core.utils.time import datetime_now
from src.infrastructure.di.providers.retort import RetortProvider


class ReferralHarness:
    def __init__(self, strategy, *, trial=False, points=False):
        self.settings = SettingsDto()
        self.settings.referral.accrual_strategy = strategy
        self.settings.referral.level = ReferralLevel.SECOND
        self.settings.referral.invitation_reward = 3
        self.settings.referral.reward.config = {ReferralLevel.FIRST: 5, ReferralLevel.SECOND: 1}
        if points:
            self.settings.referral.reward.type = ReferralRewardType.POINTS
        self.users = {
            uid: UserDto(id=uid, telegram_id=100 + uid, name=f"User {uid}", referral_code=f"r{uid}")
            for uid in (1, 2, 3)
        }
        self.subscriptions = {
            uid: SubscriptionDto(
                id=uid,
                user_id=uid,
                panel_user_id=uid,
                expire_at=datetime_now() + timedelta(days=10),
                is_trial=trial if uid == 2 else False,
                traffic_limit=0,
                device_limit=0,
                traffic_limit_strategy=TrafficLimitStrategy.NO_RESET,
                url="https://example.org/sub/test",
                plan_snapshot=PlanSnapshotDto.test(),
            )
            for uid in (1, 2)
        }
        self.initial_expiration = {uid: sub.expire_at for uid, sub in self.subscriptions.items()}
        self.referrals = {
            2: ReferralDto(
                id=10, level=ReferralLevel.FIRST, referrer=self.users[1], referred=self.users[2]
            )
        }
        self.rewards = []
        self.uow = AsyncMock()
        self.settings_dao = SimpleNamespace(
            get=AsyncMock(return_value=self.settings), update=AsyncMock()
        )
        self.user_dao = SimpleNamespace(
            get_by_id=AsyncMock(side_effect=self.users.get),
            get_by_referral_code=AsyncMock(
                side_effect=lambda code: next(
                    (user for user in self.users.values() if user.referral_code == code), None
                )
            ),
            update=AsyncMock(),
        )
        self.subscription_dao = SimpleNamespace(
            get_current=AsyncMock(side_effect=self.subscriptions.get), update=AsyncMock()
        )
        self.referral_dao = SimpleNamespace(
            get_referral_chain=AsyncMock(side_effect=self.chain),
            create_referral=AsyncMock(side_effect=self.create_referral),
            create_reward=AsyncMock(side_effect=self.create_reward),
            mark_reward_as_issued=AsyncMock(side_effect=self.mark_issued),
        )
        self.publisher = SimpleNamespace(publish=AsyncMock())
        self.panel = SimpleNamespace(update_user_expire_at=AsyncMock())
        self.give = GiveReferrerReward(
            self.uow,
            self.user_dao,
            self.subscription_dao,
            self.referral_dao,
            self.publisher,
            AddSubscriptionDuration(self.uow, self.user_dao, self.subscription_dao, self.panel),
        )
        self.attach = AttachReferral(
            self.uow,
            self.settings_dao,
            self.user_dao,
            self.referral_dao,
            self.publisher,
            self.give,
        )
        self.assign = AssignReferralRewards(
            self.uow,
            self.settings_dao,
            self.user_dao,
            self.referral_dao,
            CalculateReferralReward(),
            self.give,
        )

    def chain(self, user_id):
        referral = self.referrals.get(user_id)
        return referral, self.referrals.get(referral.referrer.id) if referral else None

    async def create_referral(self, referral):
        referral.id = 20
        self.referrals[referral.referred.id] = referral
        return referral

    async def create_reward(self, reward, referral_id):
        reward.id = len(self.rewards) + 1
        self.rewards.append((referral_id, reward))
        return reward

    async def mark_issued(self, reward_id):
        self.rewards[reward_id - 1][1].is_issued = True

    async def invite(self, user_id=3, code="r2"):
        return await self.attach.system(AttachReferralDto(user_id=user_id, referral_code=code))

    async def pay(self, purchase_type=PurchaseType.NEW, *, trial=False):
        transaction = TransactionDto(
            payment_id=uuid4(),
            user_id=3,
            status=TransactionStatus.COMPLETED,
            purchase_type=purchase_type,
            gateway_type=PaymentGatewayType.PLATEGA,
            pricing=PriceDetailsDto.test(),
            currency=Currency.RUB,
            plan_snapshot=replace(PlanSnapshotDto.test(), duration=30, is_trial=trial),
        )
        await self.assign.system(
            AssignReferralRewardsDto(user=self.users[3], transaction=transaction)
        )


@pytest.mark.parametrize(
    ("strategy", "invitation_count", "payment_count"),
    [
        (ReferralAccrualStrategy.ON_FIRST_PAYMENT, 0, 1),
        (ReferralAccrualStrategy.ON_EACH_PAYMENT, 0, 2),
        (ReferralAccrualStrategy.ON_INVITATION, 1, 0),
        (ReferralAccrualStrategy.ON_FIRST_PAYMENT_AND_INVITATION, 1, 1),
        (ReferralAccrualStrategy.ON_EACH_PAYMENT_AND_INVITATION, 1, 2),
    ],
)
async def test_all_modes_combine_independent_invitation_and_two_payment_levels(
    strategy, invitation_count, payment_count
):
    h = ReferralHarness(strategy)
    assert await h.invite() is h.users[2]
    await h.pay()
    await h.pay(PurchaseType.RENEW)

    assert h.subscriptions[2].expire_at == h.initial_expiration[2] + timedelta(
        days=3 * invitation_count + 5 * payment_count
    )
    assert h.subscriptions[1].expire_at == h.initial_expiration[1] + timedelta(days=payment_count)
    assert len(h.rewards) == invitation_count + 2 * payment_count
    assert all(reward.is_issued for _, reward in h.rewards)
    events = [
        call.args[0]
        for call in h.publisher.publish.await_args_list
        if isinstance(call.args[0], ReferralRewardReceivedEvent)
    ]
    assert sum(event.is_invitation for event in events) == invitation_count


@pytest.mark.parametrize("trial", [True, False])
async def test_invitation_days_are_added_to_trial_or_paid_subscription_once(trial):
    h = ReferralHarness(ReferralAccrualStrategy.ON_INVITATION, trial=trial)
    await h.invite()
    assert await h.invite() is None
    assert h.subscriptions[2].expire_at == h.initial_expiration[2] + timedelta(days=3)
    assert h.subscriptions[2].is_trial == trial
    assert len(h.rewards) == 1
    assert h.rewards[0][1].user_id == 2
    h.panel.update_user_expire_at.assert_awaited_once_with(2, h.subscriptions[2].expire_at)


async def test_invitation_amount_is_fixed_even_when_payment_rewards_are_percentages():
    h = ReferralHarness(ReferralAccrualStrategy.ON_EACH_PAYMENT_AND_INVITATION, points=True)
    h.settings.referral.reward.strategy = ReferralRewardStrategy.PERCENT
    h.settings.referral.invitation_reward = 17
    h.subscriptions.clear()
    await h.invite()
    assert h.users[2].points == 17
    assert h.users[1].points == 0
    await h.pay()
    assert h.users[2].points == 18
    assert h.users[1].points == 1


async def test_trial_payments_do_not_grant_extra_payment_rewards():
    h = ReferralHarness(ReferralAccrualStrategy.ON_FIRST_PAYMENT_AND_INVITATION, trial=True)
    await h.invite()
    await h.pay(trial=True)
    assert len(h.rewards) == 1
    assert h.subscriptions[2].expire_at == h.initial_expiration[2] + timedelta(days=3)


async def test_enabling_invitation_reward_does_not_reward_previously_attached_friend():
    h = ReferralHarness(ReferralAccrualStrategy.ON_FIRST_PAYMENT)
    await h.invite()
    h.settings.referral.accrual_strategy = ReferralAccrualStrategy.ON_INVITATION
    await h.invite()
    assert not h.rewards


@pytest.mark.parametrize(("user_id", "code"), [(2, "r2"), (3, "missing"), (4, "r2")])
async def test_invalid_and_self_invitations_do_not_grant_rewards(user_id, code):
    h = ReferralHarness(ReferralAccrualStrategy.ON_INVITATION)
    assert await h.invite(user_id, code) is None
    assert not h.rewards


async def test_disabled_system_does_not_attach_or_reward_invitation():
    h = ReferralHarness(ReferralAccrualStrategy.ON_INVITATION)
    h.settings.referral.enable = False
    await h.invite()
    await h.pay()
    assert not h.rewards
    h.referral_dao.create_referral.assert_not_awaited()


async def test_missing_subscription_leaves_one_unissued_reward_and_uses_invitation_notification():
    h = ReferralHarness(ReferralAccrualStrategy.ON_INVITATION)
    h.subscriptions.pop(2)
    await h.invite()
    await h.invite()
    assert len(h.rewards) == 1
    assert not h.rewards[0][1].is_issued
    event = h.publisher.publish.await_args_list[0].args[0]
    assert isinstance(event, ReferralRewardFailedEvent) and event.is_invitation
    h.panel.update_user_expire_at.assert_not_awaited()


async def test_failed_notification_does_not_break_registration_or_repeat_invitation_reward():
    h = ReferralHarness(ReferralAccrualStrategy.ON_INVITATION)
    h.publisher.publish.side_effect = RuntimeError("Notification transport unavailable")
    assert await h.invite() is h.users[2]
    await h.invite()
    assert h.rewards[0][1].is_issued
    h.panel.update_user_expire_at.assert_awaited_once()


async def test_panel_failure_keeps_referral_and_reserved_reward_without_breaking_registration():
    h = ReferralHarness(ReferralAccrualStrategy.ON_INVITATION)
    h.panel.update_user_expire_at.side_effect = TimeoutError("Panel unavailable")
    assert await h.invite() is h.users[2]
    assert 3 in h.referrals
    assert not h.rewards[0][1].is_issued
    h.referral_dao.mark_reward_as_issued.assert_not_awaited()


async def test_invitation_amount_update_preserves_payment_reward_configuration():
    h = ReferralHarness(ReferralAccrualStrategy.ON_EACH_PAYMENT_AND_INVITATION)
    update = UpdateReferralInvitationReward(h.uow, h.settings_dao)
    await update(UserDto(name="Admin", role=Role.OWNER), " 17 ")
    assert h.settings.referral.invitation_reward == 17
    assert h.settings.referral.reward.config == {ReferralLevel.FIRST: 5, ReferralLevel.SECOND: 1}
    assert "referral" in h.settings.changed_data


@pytest.mark.parametrize("value", ["", "0", "-1", "1.5", "100001", "abc", "3=5"])
async def test_invalid_invitation_amount_is_not_saved(value):
    h = ReferralHarness(ReferralAccrualStrategy.ON_INVITATION)
    update = UpdateReferralInvitationReward(h.uow, h.settings_dao)
    with pytest.raises(ValueError):
        await update(UserDto(name="Admin", role=Role.OWNER), value)
    assert h.settings.referral.invitation_reward == 3
    h.settings_dao.update.assert_not_awaited()


async def test_regular_user_cannot_change_invitation_amount():
    h = ReferralHarness(ReferralAccrualStrategy.ON_INVITATION)
    with pytest.raises(PermissionDeniedError):
        await UpdateReferralInvitationReward(h.uow, h.settings_dao)(h.users[3], "100")


@pytest.mark.parametrize("strategy", list(ReferralAccrualStrategy))
def test_existing_settings_and_new_modes_can_be_loaded_without_database_migration(strategy):
    retort = RetortProvider().get_retort()
    original = SettingsDto()
    original.referral.accrual_strategy = strategy
    dumped = retort.dump(original)
    dumped["referral"].pop("invitation_reward")
    loaded = retort.load(dumped, SettingsDto)
    assert loaded.referral.invitation_reward == 3
    assert loaded.referral.accrual_strategy == strategy
    assert loaded.referral.reward.config == {ReferralLevel.FIRST: 5}
