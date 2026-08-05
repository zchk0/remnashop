from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from src.core.enums import Locale
from src.infrastructure.services.notification import NotificationService
from src.telegram.keyboards import get_close_notification_button


def _service_without_translation() -> NotificationService:
    service = NotificationService.__new__(NotificationService)
    service._translate_keyboard_text = lambda keyboard, locale: keyboard
    return service


def _close_buttons(markup: InlineKeyboardMarkup) -> list[InlineKeyboardButton]:
    close_callback = get_close_notification_button().callback_data
    return [
        button
        for row in markup.inline_keyboard
        for button in row
        if button.callback_data == close_callback
    ]


def test_preparing_markup_repeatedly_does_not_duplicate_close_button() -> None:
    original = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="profile", callback_data="profile")],
        ]
    )
    service = _service_without_translation()

    first = service._prepare_reply_markup(original, False, None, Locale.RU, 1)
    second = service._prepare_reply_markup(original, False, None, Locale.RU, 2)

    assert isinstance(first, InlineKeyboardMarkup)
    assert isinstance(second, InlineKeyboardMarkup)
    assert len(_close_buttons(first)) == 1
    assert len(_close_buttons(second)) == 1
    assert not _close_buttons(original)


def test_existing_close_button_is_not_added_again() -> None:
    original = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="profile", callback_data="profile")],
            [get_close_notification_button()],
        ]
    )
    service = _service_without_translation()

    prepared = service._prepare_reply_markup(original, False, None, Locale.RU, 1)

    assert isinstance(prepared, InlineKeyboardMarkup)
    assert len(_close_buttons(prepared)) == 1
