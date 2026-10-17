import json
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from aiogram.enums import ButtonStyle, ChatMemberStatus
from fluent_compiler.bundle import FluentBundle
from fluentogram.translator import FluentTranslator
from remnapy.enums import TrafficLimitStrategy

from src.application.common.policy import Permission, PermissionPolicy
from src.application.dto import PlanDto, PlanSnapshotDto, SettingsDto, SubscriptionDto, UserDto
from src.application.dto.earning import (
    ChannelClaimDto,
    ChannelTaskDto,
    EarningSettingsDto,
    EarningStatisticsDto,
)
from src.application.events import EarningTaskCompletedEvent
from src.application.use_cases.earning.channels import GetEarningChannels
from src.application.use_cases.earning.manage import ManageChannelTask, UpdateEarningSettings
from src.application.use_cases.earning.rewards import (
    ClaimChannelReward,
    EarningError,
    GetEarningTasks,
    ResolveEarningClaim,
    ResolveEarningClaimDto,
)
from src.core.enums import Role, SubscriptionStatus, SystemNotificationType
from src.core.exceptions import PermissionDeniedError
from src.infrastructure.di.providers.retort import RetortProvider
from src.infrastructure.services.notification import NotificationService
from src.infrastructure.services.translator import TranslatorRunnerImpl
from src.telegram.keyboards import get_user_keyboard

NOW = datetime(2026, 10, 17, 12, tzinfo=UTC)


def subscription(**changes):
    return replace(
        SubscriptionDto(
            id=10,
            user_id=1,
            user_remna_id=uuid4(),
            panel_user_id=42,
            traffic_limit=100,
            device_limit=2,
            traffic_limit_strategy=TrafficLimitStrategy.NO_RESET,
            expire_at=NOW + timedelta(days=10),
            url="https://example.org/sub/test",
            plan_snapshot=PlanSnapshotDto.test(),
        ),
        **changes,
    )


class MemoryUow:
    def __init__(self, store):
        self.store = store

    async def __aenter__(self):
        self.snapshot = deepcopy(self.store.state)
        return self

    async def commit(self):
        self.snapshot = deepcopy(self.store.state)

    async def __aexit__(self, exc_type, exc, tb):
        if exc_type:
            self.store.state = self.snapshot


class RewardHarness:
    def __init__(self, *, sub=True, task=None, discount=0):
        self.actor = UserDto(id=1, telegram_id=123, name="User", purchase_discount=discount)
        self.settings = SettingsDto(earning=EarningSettingsDto(enabled=True, audience="all"))
        self.state = {
            "claims": {},
            "subscription": subscription() if sub else None,
            "user": deepcopy(self.actor),
        }
        self.task = task or ChannelTaskDto(
            id=1,
            channel_id=-100123,
            channel_url="https://t.me/test",
            active=True,
        )
        self.plan = PlanDto(id=7, name="Reward", is_active=True, traffic_limit=25, device_limit=1)
        self.uow = MemoryUow(self)
        self.earning_dao = SimpleNamespace(
            lock_user=AsyncMock(),
            get_task=AsyncMock(side_effect=self.get_task),
            list_tasks=AsyncMock(side_effect=self.list_tasks),
            get_claim=AsyncMock(side_effect=self.get_claim),
            get_claims=AsyncMock(side_effect=self.get_claims),
            save_claim=AsyncMock(side_effect=self.save_claim),
            save_task=AsyncMock(),
        )
        self.settings_dao = SimpleNamespace(
            get=AsyncMock(return_value=self.settings), update=AsyncMock()
        )
        self.subscription_dao = SimpleNamespace(
            get_current=AsyncMock(side_effect=lambda _: deepcopy(self.state["subscription"])),
            update=AsyncMock(side_effect=self.update_subscription),
            create=AsyncMock(side_effect=self.create_subscription),
            update_status=AsyncMock(),
        )
        self.user_dao = SimpleNamespace(
            get_by_id=AsyncMock(side_effect=lambda _: deepcopy(self.state["user"])),
            update=AsyncMock(side_effect=self.update_user),
            set_trial_available=AsyncMock(),
        )
        self.plan_dao = SimpleNamespace(get_by_id=AsyncMock(return_value=self.plan))
        self.bot_service = SimpleNamespace(
            get_chat_member=AsyncMock(return_value=SimpleNamespace(status=ChatMemberStatus.MEMBER))
        )
        remote = SimpleNamespace(
            uuid=uuid4(),
            id=42,
            subscription_url="https://example.org/sub/new",
            user_traffic=SimpleNamespace(used_traffic_bytes=0),
        )
        self.remnawave = SimpleNamespace(
            update_user_expire_at=AsyncMock(),
            enable_user=AsyncMock(),
            update_user_subscription=AsyncMock(return_value=remote),
            create_user=AsyncMock(return_value=remote),
            get_user_by_short_uuid=AsyncMock(return_value=None),
            reset_traffic=AsyncMock(return_value=remote),
            get_user_by_uuid=AsyncMock(
                return_value=SimpleNamespace(
                    user_traffic=SimpleNamespace(used_traffic_bytes=5 * 1024**3),
                )
            ),
        )
        self.event_publisher = SimpleNamespace(publish=AsyncMock())
        self.service = ClaimChannelReward(
            self.earning_dao,
            self.settings_dao,
            self.user_dao,
            self.subscription_dao,
            self.plan_dao,
            self.bot_service,
            self.remnawave,
            RetortProvider().get_retort(),
            self.uow,
            self.event_publisher,
        )

    async def get_task(self, task_id, *, lock=False):
        return (
            replace(self.task, claims_count=len(self.state["claims"]))
            if task_id == self.task.id
            else None
        )

    async def list_tasks(self):
        return [] if self.task.deleted else [await self.get_task(self.task.id)]

    async def get_claim(self, task_id, user_id):
        return deepcopy(self.state["claims"].get((task_id, user_id)))

    async def get_claims(self, user_id):
        return [
            deepcopy(claim) for claim in self.state["claims"].values() if claim.user_id == user_id
        ]

    async def save_claim(self, claim):
        # Exercise the same JSON restriction as the PostgreSQL ledger.
        json.dumps(claim.payload)
        self.state["claims"][(claim.task_id, claim.user_id)] = deepcopy(claim)

    async def update_subscription(self, sub):
        self.state["subscription"] = deepcopy(sub)
        return sub

    async def create_subscription(self, sub, user_id):
        created = replace(sub, id=20, user_id=user_id)
        self.state["subscription"] = deepcopy(created)
        return created

    async def update_user(self, user):
        self.state["user"] = deepcopy(user)
        return user

    def query(self):
        return GetEarningTasks(self.earning_dao, self.settings_dao, self.subscription_dao)


@pytest.fixture(autouse=True)
def fixed_time(monkeypatch):
    monkeypatch.setattr("src.application.use_cases.earning.rewards.datetime_now", lambda: NOW)
    monkeypatch.setattr("src.core.utils.time.datetime_now", lambda: NOW)


@pytest.mark.parametrize(
    ("audience", "role", "selected", "expected"),
    [
        ("all", Role.USER, [], True),
        ("admins", Role.USER, [], False),
        ("admins", Role.ADMIN, [], True),
        ("admins", Role.DEV, [], True),
        ("admins", Role.OWNER, [], True),
        ("selected", Role.USER, [123], True),
        ("selected", Role.ADMIN, [], False),
        ("selected", Role.USER, [999], False),
    ],
)
def test_audience(audience, role, selected, expected):
    settings = EarningSettingsDto(enabled=True, audience=audience, allowed_telegram_ids=selected)
    assert settings.allows(UserDto(telegram_id=123, name="Test", role=role)) is expected
    settings.enabled = False
    assert not settings.allows(UserDto(telegram_id=123, name="Test", role=role))


def test_blocked_and_web_users_have_no_access():
    settings = EarningSettingsDto(enabled=True, audience="all")
    assert not settings.allows(UserDto(name="Web"))
    assert not settings.allows(UserDto(name="Blocked", telegram_id=123, is_blocked=True))


async def test_combined_reward_once_and_higher_discount_preserved():
    h = RewardHarness(discount=30)
    h.task = replace(h.task, days=3, reset_traffic=True, discount=20)
    await h.service(h.actor, 1)
    assert h.state["subscription"].expire_at == NOW + timedelta(days=13)
    assert h.state["user"].purchase_discount == 30
    h.remnawave.reset_traffic.assert_awaited_once_with(42)
    assert h.state["claims"][(1, 1)].status == "completed"
    with pytest.raises(EarningError, match="already-claimed"):
        await h.service(h.actor, 1)
    h.remnawave.update_user_expire_at.assert_awaited_once()
    assert not (await h.query()(h.actor)).tasks


@pytest.mark.parametrize(
    "status", [ChatMemberStatus.LEFT, ChatMemberStatus.KICKED, ChatMemberStatus.RESTRICTED]
)
async def test_nonmembers_never_reserve_capacity(status):
    h = RewardHarness()
    h.bot_service.get_chat_member.return_value.status = status
    with pytest.raises(EarningError, match="not-subscribed"):
        await h.service(h.actor, 1)
    assert not h.state["claims"]
    h.remnawave.update_user_expire_at.assert_not_awaited()
    h.event_publisher.publish.assert_not_awaited()


@pytest.mark.parametrize("status", [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR])
async def test_channel_admins_are_members(status):
    h = RewardHarness()
    h.bot_service.get_chat_member.return_value.status = status
    await h.service(h.actor, 1)
    assert h.state["claims"][(1, 1)].status == "completed"


async def test_full_task_and_disabled_section_cannot_be_claimed():
    h = RewardHarness()
    h.task.max_claims = 1
    h.state["claims"][(1, 2)] = ChannelClaimDto(task_id=1, user_id=2, status="completed")
    assert not (await h.query()(h.actor)).tasks
    with pytest.raises(EarningError, match="full"):
        await h.service(h.actor, 1)
    h.settings.earning.enabled = False
    with pytest.raises(EarningError, match="unavailable"):
        await h.service(h.actor, 1)


async def test_discount_only_works_without_subscription():
    h = RewardHarness(sub=False)
    h.task = replace(h.task, days=0, discount=25)
    assert (await h.query()(h.actor)).tasks
    await h.service(h.actor, 1)
    assert h.state["user"].purchase_discount == 25
    assert h.state["subscription"] is None
    h.remnawave.create_user.assert_not_awaited()


async def test_days_need_subscription_or_fallback_plan():
    h = RewardHarness(sub=False)
    assert not (await h.query()(h.actor)).tasks
    with pytest.raises(EarningError, match="subscription-required"):
        await h.service(h.actor, 1)
    h.task.plan_id = 7
    assert (await h.query()(h.actor)).tasks
    await h.service(h.actor, 1)
    assert h.state["subscription"].plan_snapshot.id == 7
    assert h.state["subscription"].expire_at == NOW + timedelta(days=1)
    assert not h.state["subscription"].is_trial


async def test_trial_conversion_uses_selected_plan_days_and_preserves_remote_identity():
    h = RewardHarness()
    h.state["subscription"].is_trial = True
    h.task = replace(h.task, days=2, trial_plan_id=7, trial_days=5)
    await h.service(h.actor, 1)
    sub = h.state["subscription"]
    assert not sub.is_trial
    assert sub.plan_snapshot.id == 7
    assert sub.traffic_limit == 25
    assert sub.expire_at == NOW + timedelta(days=5)
    h.remnawave.update_user_subscription.assert_awaited_once()
    assert h.remnawave.update_user_subscription.await_args.kwargs["uuid"] == 42
    h.subscription_dao.update_status.assert_awaited_with(10, SubscriptionStatus.DELETED)


async def test_trial_without_replacement_keeps_trial_and_paid_subscription_keeps_plan():
    for is_trial in (True, False):
        h = RewardHarness()
        h.state["subscription"].is_trial = is_trial
        h.task = replace(h.task, trial_plan_id=None if is_trial else 7, trial_days=5)
        await h.service(h.actor, 1)
        assert h.state["subscription"].is_trial == is_trial
        assert h.state["subscription"].plan_snapshot.id == -1
        h.remnawave.update_user_subscription.assert_not_awaited()


async def test_expired_days_start_from_now_and_disabled_subscription_stays_disabled():
    for status in (SubscriptionStatus.EXPIRED, SubscriptionStatus.DISABLED):
        h = RewardHarness()
        h.state["subscription"] = subscription(expire_at=NOW - timedelta(days=30), status=status)
        await h.service(h.actor, 1)
        assert h.state["subscription"].expire_at == NOW + timedelta(days=1)
        if status == SubscriptionStatus.DISABLED:
            assert h.state["subscription"].status == SubscriptionStatus.DISABLED
            h.remnawave.enable_user.assert_not_awaited()
        else:
            assert h.state["subscription"].status == SubscriptionStatus.ACTIVE
            h.remnawave.enable_user.assert_awaited_once()


async def test_remote_timeout_retries_absolute_expiration_without_rechecking_membership():
    h = RewardHarness()
    h.remnawave.update_user_expire_at.side_effect = [TimeoutError("lost reply"), None]
    with pytest.raises(TimeoutError):
        await h.service(h.actor, 1)
    h.event_publisher.publish.assert_not_awaited()
    claim = h.state["claims"][(1, 1)]
    assert claim.status == "pending"
    assert not claim.subscription_applied
    assert (await h.query()(h.actor)).tasks
    await h.service(h.actor, 1)
    calls = h.remnawave.update_user_expire_at.await_args_list
    assert calls[0] == calls[1]
    assert h.state["subscription"].expire_at == NOW + timedelta(days=11)
    h.bot_service.get_chat_member.assert_awaited_once()
    h.event_publisher.publish.assert_awaited_once()
    event = h.event_publisher.publish.await_args.args[0]
    assert event.subscription_before.expire_at == NOW + timedelta(days=10)
    assert event.subscription_after.expire_at == NOW + timedelta(days=11)


async def test_reset_lost_reply_requires_review_instead_of_repeating_reset():
    h = RewardHarness()
    h.task.reset_traffic = True
    h.remnawave.reset_traffic.side_effect = TimeoutError("lost reply")
    with pytest.raises(TimeoutError):
        await h.service(h.actor, 1)
    assert h.state["subscription"].expire_at == NOW + timedelta(days=11)
    assert h.state["claims"][(1, 1)].reset_started
    with pytest.raises(EarningError, match="review-required"):
        await h.service(h.actor, 1)
    h.remnawave.reset_traffic.assert_awaited_once()
    h.remnawave.update_user_expire_at.assert_awaited_once()
    h.event_publisher.publish.assert_not_awaited()


async def test_admin_can_confirm_reset_and_finish_discount_without_repeating_days():
    h = RewardHarness()
    h.task = replace(h.task, reset_traffic=True, discount=25)
    h.remnawave.reset_traffic.side_effect = TimeoutError()
    with pytest.raises(TimeoutError):
        await h.service(h.actor, 1)
    resolve = ResolveEarningClaim(h.earning_dao, h.user_dao, h.uow, h.service)
    with pytest.raises(PermissionDeniedError):
        await resolve(h.actor, ResolveEarningClaimDto(task_id=1, user_id=1, confirm_reset=True))
    await resolve(
        replace(h.actor, role=Role.ADMIN),
        ResolveEarningClaimDto(
            task_id=1,
            user_id=1,
            confirm_reset=True,
        ),
    )
    assert h.state["claims"][(1, 1)].status == "completed"
    assert h.state["user"].purchase_discount == 25
    assert h.state["subscription"].expire_at == NOW + timedelta(days=11)
    h.remnawave.reset_traffic.assert_awaited_once()
    h.remnawave.update_user_expire_at.assert_awaited_once()
    h.event_publisher.publish.assert_awaited_once()
    event = h.event_publisher.publish.await_args.args[0]
    assert event.subscription_before.expire_at == NOW + timedelta(days=10)
    assert event.subscription_after.expire_at == NOW + timedelta(days=11)
    assert event.discount_before == 0 and event.discount_after == 25
    assert event.traffic_before == 5 * 1024**3


async def test_traffic_only_reward_restores_limited_status():
    h = RewardHarness()
    h.task = replace(h.task, days=0, reset_traffic=True)
    h.state["subscription"].status = SubscriptionStatus.LIMITED
    await h.service(h.actor, 1)
    h.subscription_dao.update_status.assert_awaited_once_with(10, SubscriptionStatus.ACTIVE)
    h.remnawave.update_user_expire_at.assert_not_awaited()


async def test_retry_uses_reward_snapshot_even_after_task_edit_and_deletion():
    h = RewardHarness()
    h.remnawave.update_user_expire_at.side_effect = TimeoutError()
    with pytest.raises(TimeoutError):
        await h.service(h.actor, 1)
    original_title = h.task.title
    h.task = replace(h.task, title="Changed task", days=99, discount=90, active=False, deleted=True)
    pending = (await h.query()(h.actor)).tasks
    assert len(pending) == 1 and pending[0].days == 1 and pending[0].discount == 0
    h.remnawave.update_user_expire_at.side_effect = None
    await h.service(h.actor, 1)
    assert h.state["subscription"].expire_at == NOW + timedelta(days=11)
    assert h.state["user"].purchase_discount == 0
    event = h.event_publisher.publish.await_args.args[0]
    assert event.days == 1 and event.discount == 0
    assert event.channel_title == original_title


async def test_changed_subscription_is_never_overwritten_on_retry():
    h = RewardHarness()
    await h.service._reserve(h.actor, 1)
    h.state["subscription"].expire_at += timedelta(days=100)
    with pytest.raises(EarningError, match="review-required"):
        await h.service(h.actor, 1)
    h.remnawave.update_user_expire_at.assert_not_awaited()


async def test_pending_other_task_prevents_lost_days():
    h = RewardHarness()
    h.state["claims"][(2, 1)] = ChannelClaimDto(task_id=2, user_id=1)
    with pytest.raises(EarningError, match="finish-pending"):
        await h.service(h.actor, 1)


async def test_task_and_settings_management_requires_admin_and_tracks_full_settings():
    h = RewardHarness()
    manage = ManageChannelTask(h.earning_dao, h.plan_dao, h.uow)
    update = UpdateEarningSettings(h.settings_dao, h.uow)
    with pytest.raises(PermissionDeniedError):
        await manage(h.actor, h.task)
    with pytest.raises(PermissionDeniedError):
        await update(h.actor, {"enabled": False})
    admin = replace(h.actor, role=Role.ADMIN)
    await update(
        admin,
        {
            "audience": "selected",
            "allowed_telegram_ids": [123],
            "button_color": ButtonStyle.PRIMARY,
            "button_text": "Награды",
        },
    )
    assert h.settings.earning.button_text == "Награды"
    assert "earning" in h.settings.changed_data
    assert PermissionPolicy.has_permission(admin, Permission.MANAGE_EARNING)


@pytest.mark.parametrize(
    "changes",
    [
        {"days": -1},
        {"discount": 101},
        {"max_claims": 0},
        {"trial_days": -2},
        {"days": 0, "discount": 0, "reset_traffic": False},
        {"channel_url": "https://example.org/channel"},
    ],
)
async def test_admin_validation_rejects_invalid_active_task(changes):
    h = RewardHarness()
    admin = replace(h.actor, role=Role.ADMIN)
    manage = ManageChannelTask(h.earning_dao, h.plan_dao, h.uow)
    with pytest.raises(ValueError):
        await manage(admin, replace(h.task, **changes))
    h.earning_dao.save_task.assert_not_awaited()


def test_old_settings_load_defaults_and_new_settings_roundtrip():
    retort = RetortProvider().get_retort()
    assert not retort.load({}, EarningSettingsDto).enabled
    settings = EarningSettingsDto(enabled=True, audience="selected", allowed_telegram_ids=[123])
    assert retort.load(retort.dump(settings), EarningSettingsDto) == settings


def test_all_earning_translation_keys_compile_and_advertising_terms_are_visible():
    source = Path("assets/translations/ru/earning.ftl").read_text("utf-8")
    translator = FluentTranslator(
        locale="ru",
        translator=FluentBundle.from_string(
            locale="ru",
            text=source,
            use_isolating=False,
        ),
    )
    advert = translator.get("msg-earning-advertise", price="10 ₽")
    assert "10 ₽" in advert and "15 подписчиков" in advert
    assert "проверяет подписку при выполнении" in advert
    for key in ("msg-earning-main", "msg-earning-input-channel", "earning-reward-reset"):
        assert translator.get(key)


async def test_channel_counters_use_successful_completions_and_exclude_paused_tasks():
    tasks = [
        ChannelTaskDto(active=True),
        ChannelTaskDto(active=True, max_claims=2, claims_count=2, completed_claims_count=1),
        ChannelTaskDto(active=True, max_claims=2, claims_count=2, completed_claims_count=2),
        ChannelTaskDto(active=False, max_claims=1, claims_count=1, completed_claims_count=1),
        ChannelTaskDto(active=False),
    ]
    dao = SimpleNamespace(
        list_tasks=AsyncMock(return_value=tasks),
        get_statistics=AsyncMock(
            return_value=EarningStatisticsDto(
                daily=1,
                weekly=2,
                monthly=3,
                total=4,
            )
        ),
    )
    service = GetEarningChannels(dao)
    with pytest.raises(PermissionDeniedError):
        await service(UserDto(name="User"))
    result = await service(UserDto(name="Admin", role=Role.ADMIN))
    assert result.statistics == EarningStatisticsDto(
        daily=1,
        weekly=2,
        monthly=3,
        total=4,
        active_tasks=2,
        completed_tasks=2,
    )


@pytest.fixture(scope="module")
def earning_event_translator():
    translator = FluentTranslator(
        locale="ru",
        translator=FluentBundle.from_string(
            locale="ru",
            text="\n".join(
                path.read_text("utf-8")
                for path in sorted(Path("assets/translations/ru").glob("*.ftl"))
            ),
            use_isolating=False,
        ),
    )
    return TranslatorRunnerImpl([translator], RetortProvider().get_retort())


def render_earning_event(translator, event):
    payload = event.as_payload()
    return translator.get(payload.i18n_key, **payload.i18n_kwargs)


async def test_completion_event_is_published_after_commit_once_with_actual_changes(
    earning_event_translator,
):
    h = RewardHarness(discount=30)
    h.task = replace(h.task, days=3, reset_traffic=True, discount=20)

    async def assert_committed(event):
        assert h.uow.snapshot["claims"][(1, 1)].status == "completed"
        assert h.uow.snapshot["subscription"].expire_at == NOW + timedelta(days=13)

    h.event_publisher.publish.side_effect = assert_committed
    await h.service(h.actor, 1)
    event = h.event_publisher.publish.await_args.args[0]
    assert isinstance(event, EarningTaskCompletedEvent)
    assert event.notification_type == SystemNotificationType.EARNING_TASK_COMPLETED
    assert event.user_id == h.actor.id and event.telegram_id == 123
    assert event.task_id == 1 and event.channel_id == h.task.channel_id
    assert event.subscription_before.expire_at == NOW + timedelta(days=10)
    assert event.subscription_after.expire_at == NOW + timedelta(days=13)
    assert event.traffic_before == 5 * 1024**3 and event.traffic_after == 0
    assert event.discount_before == event.discount_after == 30
    text = render_earning_event(earning_event_translator, event)
    assert text.count("<blockquote>") == text.count("</blockquote>") == 3
    assert "27.10.2026 12:00 UTC → 30.10.2026 12:00 UTC" in text
    assert "5 ГБ → 0 ГБ" in text
    assert "30% → 30%" in text
    assert "<code>123</code>" in text and "<code>-100123</code>" in text
    assert "!empty!" not in text
    with pytest.raises(EarningError, match="already-claimed"):
        await h.service(h.actor, 1)
    h.event_publisher.publish.assert_awaited_once()


async def test_trial_conversion_notification_shows_plan_type_and_limit_changes_and_escapes_html(
    earning_event_translator,
):
    h = RewardHarness()
    h.state["user"].name = "<Alice & Bob>"
    h.state["subscription"].is_trial = True
    h.state["subscription"].plan_snapshot.name = "Trial"
    h.plan.name = "Premium <VIP>"
    h.task = replace(h.task, title="News <&>", days=2, trial_plan_id=7, trial_days=5)
    await h.service(h.actor, 1)
    event = h.event_publisher.publish.await_args.args[0]
    assert event.days == 5
    text = render_earning_event(earning_event_translator, event)
    assert "Дни подписки</b>: +5" in text
    assert "Trial → Premium &lt;VIP&gt;" in text
    assert "Пробная → Обычная" in text
    assert "100 ГБ → 25 ГБ" in text
    assert "2 устройства → 1 устройство" in text
    assert "&lt;Alice &amp; Bob&gt;" in text
    assert 'href="https://t.me/test">News &lt;&amp;&gt;</a>' in text
    assert "Скидка" not in text and "Сброс трафика" not in text


async def test_notification_for_new_subscription_shows_no_previous_subscription(
    earning_event_translator,
):
    h = RewardHarness(sub=False)
    h.task.plan_id = 7
    await h.service(h.actor, 1)
    event = h.event_publisher.publish.await_args.args[0]
    assert event.subscription_before is None
    assert event.subscription_before_known
    text = render_earning_event(earning_event_translator, event)
    assert "Нет подписки → Reward" in text
    assert "Нет подписки → 18.10.2026 12:00 UTC" in text
    assert "Нет подписки → 25 ГБ" in text


async def test_discount_only_notification_uses_fresh_discount_and_has_no_subscription_rows(
    earning_event_translator,
):
    h = RewardHarness(sub=False, discount=5)
    h.task = replace(h.task, days=0, discount=25)
    h.state["user"].purchase_discount = 10
    await h.service(h.actor, 1)
    text = render_earning_event(
        earning_event_translator, h.event_publisher.publish.await_args.args[0]
    )
    assert "10% → 25%" in text
    assert "Срок подписки" not in text and "Тариф" not in text
    assert "Дни подписки" not in text and "Сброс трафика" not in text
    h.remnawave.get_user_by_uuid.assert_not_awaited()


async def test_unknown_traffic_does_not_block_reward_or_pretend_to_be_unlimited(
    earning_event_translator,
):
    h = RewardHarness()
    h.task = replace(h.task, days=0, reset_traffic=True)
    h.remnawave.get_user_by_uuid.side_effect = TimeoutError()
    await h.service(h.actor, 1)
    event = h.event_publisher.publish.await_args.args[0]
    assert event.traffic_before is None and event.traffic_after == 0
    text = render_earning_event(earning_event_translator, event)
    assert "Нет данных → 0 ГБ" in text
    assert "Срок подписки" not in text and "Скидка" not in text
    h.remnawave.reset_traffic.assert_awaited_once()


async def test_old_pending_claim_without_before_snapshot_can_finish(earning_event_translator):
    h = RewardHarness()
    await h.service._reserve(h.actor, 1)
    h.state["claims"][(1, 1)].payload.pop("subscription_before")
    await h.service(h.actor, 1)
    event = h.event_publisher.publish.await_args.args[0]
    assert not event.subscription_before_known
    text = render_earning_event(earning_event_translator, event)
    assert "Нет данных → 28.10.2026 12:00 UTC" in text


async def test_failed_notification_does_not_report_failed_reward_or_allow_another_claim():
    h = RewardHarness()
    h.event_publisher.publish.side_effect = RuntimeError("notification unavailable")
    await h.service(h.actor, 1)
    assert h.state["claims"][(1, 1)].status == "completed"
    assert h.state["subscription"].expire_at == NOW + timedelta(days=11)
    with pytest.raises(EarningError, match="already-claimed"):
        await h.service(h.actor, 1)
    h.event_publisher.publish.assert_awaited_once()


async def test_failed_completion_commit_never_publishes_success():
    h = RewardHarness()
    commit = h.uow.commit
    calls = 0

    async def failing_final_commit():
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("commit failed")
        await commit()

    h.uow.commit = failing_final_commit
    with pytest.raises(RuntimeError, match="commit failed"):
        await h.service(h.actor, 1)
    assert h.state["claims"][(1, 1)].status == "pending"
    h.event_publisher.publish.assert_not_awaited()


@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("destination", ["admins", "default_route", "event_route"])
async def test_completion_notification_uses_existing_settings_routes_and_user_button(
    enabled,
    destination,
    earning_event_translator,
):
    h = RewardHarness()
    await h.service(h.actor, 1)
    event = h.event_publisher.publish.await_args.args[0]
    notifications = h.settings.notifications
    # Existing saved settings lack this new key and should still list the event.
    notifications.settings.pop(str(event.notification_type), None)
    assert (event.notification_type, True) in notifications.system
    assert (
        earning_event_translator.get("notification-type", notification_type=event.notification_type)
        == "Выполнение задания"
    )
    if not enabled:
        notifications.toggle(event.notification_type)
    if destination == "default_route":
        notifications.set_default_route(-100777, 15)
    elif destination == "event_route":
        notifications.set_default_route(-100777, 15)
        notifications.set_route(event.notification_type, -100999, 25)

    service = NotificationService.__new__(NotificationService)
    service.settings_dao = h.settings_dao
    service.notify_admins = AsyncMock()
    service._send_to_route = AsyncMock()
    await service.on_system_event(event)
    if not enabled:
        service.notify_admins.assert_not_awaited()
        service._send_to_route.assert_not_awaited()
        return
    if destination == "admins":
        service.notify_admins.assert_awaited_once()
        payload = service.notify_admins.await_args.args[0]
    else:
        service._send_to_route.assert_awaited_once()
        payload, route = service._send_to_route.await_args.args
        assert route.chat_id == (-100999 if destination == "event_route" else -100777)
        assert route.thread_id == (25 if destination == "event_route" else 15)
    assert payload.reply_markup == get_user_keyboard(h.actor.id)
    assert payload.delete_after is None and not payload.disable_default_markup
