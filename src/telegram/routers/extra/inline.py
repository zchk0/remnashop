import hashlib

from aiogram import F, Router
from aiogram.enums import ButtonStyle
from aiogram.types import (
    InlineKeyboardButton,
    InlineQuery,
    InlineQueryResultArticle,
    InlineQueryResultPhoto,
    InlineQueryResultUnion,
    InputTextMessageContent,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from dishka import FromDishka
from dishka.integrations.aiogram_dialog import inject
from loguru import logger

from src.application.common import BotService, TranslatorRunner
from src.application.common.dao import UserDao
from src.core.config import AppConfig
from src.core.constants import API_V1, BANNERS_PATH, INLINE_QUERY_INVITE
from src.core.enums import BannerName, Locale
from src.telegram.widgets.banner import get_banner

router = Router(name=__name__)


def get_public_banner_url(config: AppConfig, user_language: Locale) -> str | None:
    if not config.bot.use_banners:
        return None

    try:
        banner_path, _ = get_banner(
            banners_dir=config.banners_dir,
            default_banners_dir=config.default_banners_dir,
            name=BannerName.MENU,
            locale=user_language,
            default_locale=config.default_locale,
        )
    except FileNotFoundError:
        logger.critical(f"Failed to resolve inline invite banner '{BannerName.MENU}'")
        return None

    extension = banner_path.suffix.lstrip(".").lower()
    domain = config.bot_webhook_domain.get_secret_value()
    return f"https://{domain}{API_V1}{BANNERS_PATH}/{user_language}/{BannerName.MENU}.{extension}"


@inject
@router.inline_query(F.query == INLINE_QUERY_INVITE)
async def handle_inline_query(
    inline_query: InlineQuery,
    user_dao: FromDishka[UserDao],
    bot_service: FromDishka[BotService],
    i18n: FromDishka[TranslatorRunner],
    config: FromDishka[AppConfig],
) -> None:
    user = await user_dao.get_by_telegram_id(inline_query.from_user.id)

    if not user:
        logger.warning(
            f"User with Telegram ID '{inline_query.from_user.id}' not found for inline query"
        )
        return

    logger.info(f"{user.log} Sent inline query {INLINE_QUERY_INVITE}")

    result_id = hashlib.md5(inline_query.query.strip().encode()).hexdigest()
    referral_url = await bot_service.get_referral_url(user.referral_code)
    bot_name = await bot_service.get_my_name()
    message_text = i18n.get("inline-invite.message", bot_name=bot_name)

    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text=i18n.get("inline-invite.start"),
            style=ButtonStyle.SUCCESS,
            url=referral_url,
        )
    )

    banner_url = get_public_banner_url(config=config, user_language=user.language)
    if banner_url:
        result: InlineQueryResultUnion = InlineQueryResultPhoto(
            id=result_id,
            photo_url=banner_url,
            thumbnail_url=banner_url,
            title=i18n.get("inline-invite.title"),
            description=i18n.get("inline-invite.description"),
            caption=message_text,
            reply_markup=builder.as_markup(),
        )
    else:
        result = InlineQueryResultArticle(
            id=result_id,
            thumbnail_url=(
                "https://encrypted-tbn0.gstatic.com/images?"
                "q=tbn:ANd9GcT6Msm80-vY25Ecm4cOhOTAG1P21zKBax8-KA&s"
            ),
            title=i18n.get("inline-invite.title"),
            description=i18n.get("inline-invite.description"),
            input_message_content=InputTextMessageContent(message_text=message_text),
            reply_markup=builder.as_markup(),
        )

    await inline_query.answer([result], cache_time=1, is_personal=True)
