import base64
from io import BytesIO
from typing import Any, Optional, cast

from aiogram.types import Message, TelegramObject
from loguru import logger
from PIL import Image
from qrcode import ERROR_CORRECT_H, QRCode  # type: ignore[attr-defined]

from src.application.common import Interactor
from src.application.common.dao import UserDao
from src.application.dto import UserDto
from src.core.constants import ASSETS_DIR, REFERRAL_PREFIX


class ValidateReferralCode(Interactor[str, bool]):
    required_permission = None

    def __init__(self, user_dao: UserDao) -> None:
        self.user_dao = user_dao

    async def _execute(self, actor: UserDto, referral_code: str) -> bool:
        referrer = await self.user_dao.get_by_referral_code(referral_code)
        if not referrer or referrer.telegram_id == actor.telegram_id:
            logger.warning(
                f"Invalid referral code '{referral_code}' or self-referral by '{actor.telegram_id}'"
            )
            return False
        return True


class GetReferralCodeFromEvent(Interactor[TelegramObject, Optional[str]]):
    required_permission = None

    def __init__(self, user_dao: UserDao, validate_referral_code: ValidateReferralCode) -> None:
        self.user_dao = user_dao
        self.validate_referral_code = validate_referral_code

    async def _execute(self, actor: UserDto, event: TelegramObject) -> Optional[str]:
        if not isinstance(event, Message) or not event.text:
            return None

        parts = event.text.split()
        if len(parts) <= 1:
            return None

        code = parts[1]
        if code.startswith(REFERRAL_PREFIX):
            logger.debug(f"Detected referral event '{code}'")
            code = code[len(REFERRAL_PREFIX) :]

            if await self.validate_referral_code.system(code):
                return code

        return None


class GenerateReferralQr(Interactor[str, str]):
    required_permission = None

    async def _execute(self, actor: UserDto, url: str) -> str:
        qr: Any = QRCode(
            version=1,
            error_correction=ERROR_CORRECT_H,
            box_size=10,
            border=4,
        )

        qr.add_data(url)
        qr.make(fit=True)

        qr_img_raw = qr.make_image(fill_color="black", back_color="white")

        if hasattr(qr_img_raw, "get_image"):
            qr_img = cast(Image.Image, qr_img_raw.get_image())
        else:
            qr_img = cast(Image.Image, qr_img_raw)

        qr_img = qr_img.convert("RGB")

        logo_path = ASSETS_DIR / "logo.png"
        if logo_path.exists():
            logo = Image.open(logo_path).convert("RGBA")

            qr_width, qr_height = qr_img.size
            logo_size = int(qr_width * 0.2)
            logo = logo.resize((logo_size, logo_size), resample=Image.Resampling.LANCZOS)

            pos = ((qr_width - logo_size) // 2, (qr_height - logo_size) // 2)
            qr_img.paste(logo, pos, mask=logo)

        buffer = BytesIO()
        qr_img.save(buffer, format="PNG")
        qr_bytes = buffer.getvalue()
        qr_base64 = base64.b64encode(qr_bytes).decode("ascii")
        buffer.seek(0)

        logger.info(f"{actor.log} Generated referral QR for URL '{url}'")

        return qr_base64
