import html
import re
from typing import Optional
from urllib.parse import quote

from aiogram import Bot

from src.core.config import AppConfig
from src.core.constants import T_ME
from src.core.enums import Deeplink


class BotService:
    def __init__(self, bot: Bot, config: AppConfig):
        self.bot = bot
        self.config = config
        self._bot_username: Optional[str] = None
        self._can_join_groups: Optional[bool] = None
        self._can_read_all_group_messages: Optional[bool] = None
        self._supports_inline: Optional[bool] = None

    async def _update_bot_info(self) -> None:
        if self._bot_username is None:
            me = await self.bot.get_me()
            self._bot_username = me.username
            self._can_join_groups = me.can_join_groups
            self._can_read_all_group_messages = me.can_read_all_group_messages
            self._supports_inline = me.supports_inline_queries

    async def _get_bot_redirect_url(self) -> str:
        await self._update_bot_info()
        return f"{T_ME}{self._bot_username}"

    async def is_inline_enabled(self) -> bool:
        await self._update_bot_info()
        return self._supports_inline or False

    async def get_bot_states(self) -> dict[str, str]:
        bot_info = await self.bot.get_me()

        status_map: dict[Optional[bool], str] = {
            True: "Enabled",
            False: "Disabled",
            None: "Unknown",
        }

        return {
            "groups_mode": status_map[bot_info.can_join_groups],
            "privacy_mode": status_map[not bot_info.can_read_all_group_messages],
            "inline_mode": status_map[bot_info.supports_inline_queries],
        }

    async def get_my_name(self) -> str:
        result = await self.bot.get_my_name()
        return result.name

    async def get_referral_url(self, referral_code: str) -> str:
        base_url = await self._get_bot_redirect_url()
        return Deeplink.REFERRAL.build_url(base_url, referral_code)

    async def get_plan_url(self, public_code: str) -> str:
        base_url = await self._get_bot_redirect_url()
        return Deeplink.PLAN.build_url(base_url, public_code)

    async def get_purchase_url(self, plan_id: int, duration_days: int) -> str:
        base_url = await self._get_bot_redirect_url()
        return Deeplink.BUY.build_url(base_url, f"{plan_id}_{duration_days}")

    @staticmethod
    def _prepare_support_text(text: Optional[str]) -> str:
        if not text:
            return ""
        # Telegram prefilled chat text does not parse bot-style HTML tags.
        plain_text = re.sub(r"</?[^>]+>", "", text)
        return html.unescape(plain_text)

    def get_support_url(self, text: Optional[str] = None) -> str:
        if self.config.bot.support_url:
            base_url = self.config.bot.support_url.get_secret_value()
        elif self.config.bot.support_username:
            base_url = f"{T_ME}{self.config.bot.support_username.get_secret_value()}"
        else:
            raise ValueError("Support URL is not configured")

        encoded_text = quote(self._prepare_support_text(text))
        if not encoded_text:
            return base_url

        separator = "&" if "?" in base_url else "?"
        return f"{base_url}{separator}text={encoded_text}"
