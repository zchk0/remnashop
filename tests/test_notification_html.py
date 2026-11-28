from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from xml.etree.ElementTree import fromstring

import pytest
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.formatting import Bold, Text
from fluent_compiler.bundle import FluentBundle
from fluentogram.translator import FluentTranslator

from src.application.dto import MediaDescriptorDto, SystemNotificationRouteDto, TempUserDto, UserDto
from src.application.events import ErrorEvent
from src.application.events.system import (
    ChannelCheckErrorEvent,
    NodeConnectionLostEvent,
    NotificationErrorEvent,
    PromocodeActivatedEvent,
    TrialActivatedEvent,
    UserDeviceAddedEvent,
    UserRegisteredEvent,
    WebhookErrorEvent,
)
from src.application.events.user import ReferralAttachedEvent
from src.core.constants import RAW_BUTTON_TEXT_PREFIX, USER_KEY
from src.core.enums import Locale, MediaType, PlanType
from src.core.utils.i18n_helpers import i18n_format_days, i18n_format_traffic_limit
from src.infrastructure.di.providers.retort import RetortProvider
from src.infrastructure.services.notification import NotificationService
from src.infrastructure.services.translator import TranslatorRunnerImpl
from src.telegram.routers.dashboard.broadcast.handlers import on_link_preview_toggle, on_preview

NAME = '<🐈 Alice & "Bob">'
REASON = 'Bad Request: Unsupported start tag "<invalid>" & connection failed'


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
        [FluentTranslator(locale="ru", translator=bundle)], RetortProvider().get_retort()
    )


def plain_text(html):
    return "".join(fromstring(f"<root>{html}</root>").itertext())


@pytest.mark.parametrize(
    ("event", "expected"),
    [
        (
            UserRegisteredEvent(
                telegram_id=123,
                name=NAME,
                referrer_user_id=7,
                referrer_telegram_id=456,
                referrer_name="<Referrer & Co>",
                ad_link_id=8,
                ad_link_name="<Campaign & Co>",
                ad_link_code="<code>&",
            ),
            [NAME, "<Referrer & Co>", "<Campaign & Co>", "<code>&"],
        ),
        (
            UserRegisteredEvent(name=NAME, email="<mail>&@example.com"),
            [NAME, "<mail>&@example.com"],
        ),
        (
            UserDeviceAddedEvent(
                telegram_id=123,
                name=NAME,
                hwid="<device>&",
                platform="<platform>&",
                device_model="<model>&",
                os_version="<os>&",
                user_agent="<agent>&",
            ),
            [NAME, "<device>&", "<platform>&", "<model>&", "<os>&", "<agent>&"],
        ),
        (
            TrialActivatedEvent(
                telegram_id=123,
                name=NAME,
                plan_name="Premium <VIP> & Co",
                plan_type=PlanType.BOTH,
                plan_traffic_limit=i18n_format_traffic_limit(25),
                plan_device_limit=2,
                plan_duration=i18n_format_days(3),
            ),
            [NAME, "Premium <VIP> & Co", "25 ГБ", "3 дня"],
        ),
        (
            PromocodeActivatedEvent(
                user_id=1,
                telegram_id=123,
                username=None,
                name=NAME,
                promocode_code="<PROMO>&",
                reward_type="SUBSCRIPTION",
                reward=None,
                plan_name="Plan <VIP>&",
            ),
            [NAME, "<PROMO>&", "Plan <VIP>&"],
        ),
        (
            ChannelCheckErrorEvent(telegram_id=123, username=None, name=NAME, reason=REASON),
            [NAME, REASON],
        ),
        (
            NotificationErrorEvent(chat_id=-1003907557005, thread_id=4, reason=REASON),
            ["-1003907557005:4", REASON],
        ),
        (WebhookErrorEvent(error_message=REASON), [REASON]),
        (
            NodeConnectionLostEvent(
                country="RU",
                name="Node <RU>&",
                address="node.example.com",
                port=2222,
                traffic_used=0,
                traffic_limit=i18n_format_traffic_limit(25),
                last_status_message=REASON,
                last_status_change=None,
            ),
            ["Node <RU>&", REASON, "25 ГБ", ":2222"],
        ),
        (
            ReferralAttachedEvent(user=UserDto(name=NAME), name=NAME),
            [NAME],
        ),
    ],
)
def test_event_data_is_literal_text_in_html_notifications(translator, event, expected):
    payload = event.as_payload()
    rendered = translator.get(payload.i18n_key, **payload.i18n_kwargs)
    visible = plain_text(rendered)

    for value in expected:
        assert value in visible
    assert "<b>" in rendered and "<blockquote>" in rendered
    # Rendering repeatedly must not escape the event's source data in place.
    assert event.as_payload().i18n_kwargs == payload.i18n_kwargs


def test_error_notification_escapes_identity_and_preserves_formatted_error(translator):
    event = ErrorEvent(telegram_id=123, name=NAME, exception=RuntimeError(REASON))
    payload = event.as_payload(
        MediaDescriptorDto(kind="bytes", value="", filename="error.txt"),
        "RuntimeError",
        Text(REASON, " ", Bold("details")),
    )
    rendered = translator.get(payload.i18n_key, **payload.i18n_kwargs)

    assert NAME in plain_text(rendered)
    assert REASON in plain_text(rendered)
    assert "<b>details</b>" in rendered
    assert event.name == NAME


@pytest.mark.parametrize("destination", ["route", "user"])
@pytest.mark.parametrize("media_type", [None, MediaType.DOCUMENT])
async def test_notification_delivery_preserves_safe_html(translator, destination, media_type):
    bot = AsyncMock()
    publisher = AsyncMock()
    service = NotificationService(
        bot=bot,
        config=SimpleNamespace(default_locale=Locale.RU),
        translator_hub=SimpleNamespace(get_translator_by_locale=lambda locale: translator),
        user_dao=AsyncMock(),
        settings_dao=AsyncMock(),
        worker=AsyncMock(),
        event_publisher=publisher,
    )
    payload = UserRegisteredEvent(telegram_id=123, name=NAME).as_payload()
    if media_type:
        payload = replace(
            payload,
            media_type=media_type,
            media=MediaDescriptorDto(kind="bytes", value="", filename="notice.txt"),
            link_preview_enabled=True,
        )
    if destination == "route":
        await service._send_to_route(
            payload, SystemNotificationRouteDto(chat_id=-1003907557005, thread_id=4)
        )
    else:
        await service.notify_user(TempUserDto(telegram_id=123, name="Owner"), payload)

    sender = bot.send_document if media_type else bot.send_message
    sender.assert_awaited_once()
    sent = sender.await_args.kwargs
    assert NAME in plain_text(sent["caption" if media_type else "text"])
    if media_type:
        assert "link_preview_options" not in sent
    else:
        assert sent["link_preview_options"].is_disabled is True
    if destination == "route":
        assert sent["message_thread_id"] == 4
    publisher.publish.assert_not_awaited()


@pytest.mark.parametrize("button_url", [None, "https://t.me/example/1"])
async def test_broadcast_link_preview_uses_the_saved_toggle(translator, button_url):
    keyboard = [[InlineKeyboardButton(text="btn-menu.support", url="https://example.com/help")]]
    if button_url:
        button = InlineKeyboardButton(text=f"{RAW_BUTTON_TEXT_PREFIX}Open", url=button_url)
        keyboard.append([button])
    draft = {
        "i18n_key": "raw-message",
        "i18n_kwargs": {"content": "Read https://example.com/news"},
        "reply_markup": InlineKeyboardMarkup(inline_keyboard=keyboard).model_dump(),
        "delete_after": None,
    }
    manager = SimpleNamespace(
        dialog_data={"payload": draft, "broadcast_confirm": 123},
        middleware_data={USER_KEY: UserDto(telegram_id=123, name="Admin")},
    )
    retort = RetortProvider().get_retort()
    bot = AsyncMock()
    notifier = NotificationService(
        bot=bot,
        config=SimpleNamespace(default_locale=Locale.RU),
        translator_hub=SimpleNamespace(get_translator_by_locale=lambda locale: translator),
        user_dao=AsyncMock(),
        settings_dao=AsyncMock(),
        worker=AsyncMock(),
        event_publisher=AsyncMock(),
    )

    await on_link_preview_toggle.__dishka_orig_func__(None, None, manager, retort)
    await on_preview.__dishka_orig_func__(None, None, manager, retort, notifier)
    sent = bot.send_message.await_args.kwargs
    assert sent["link_preview_options"].is_disabled is False
    assert sent["link_preview_options"].url == button_url
    assert sent["text"] == draft["i18n_kwargs"]["content"]
    assert "broadcast_confirm" not in manager.dialog_data

    await on_link_preview_toggle.__dishka_orig_func__(None, None, manager, retort)
    await on_preview.__dishka_orig_func__(None, None, manager, retort, notifier)
    assert bot.send_message.await_args.kwargs["link_preview_options"].is_disabled is True
