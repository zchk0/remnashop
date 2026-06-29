from pathlib import Path

from dishka import FromDishka
from dishka.integrations.fastapi import inject
from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse
from loguru import logger

from src.core.config import AppConfig
from src.core.constants import API_V1, BANNERS_PATH
from src.core.enums import BannerFormat, BannerName, Locale
from src.telegram.widgets.banner import get_banner

router = APIRouter(prefix=API_V1 + BANNERS_PATH)


@router.get("/{locale}/{filename}")
@inject
async def banner(
    locale: str,
    filename: str,
    config: FromDishka[AppConfig],
) -> FileResponse:
    requested_file = Path(filename)

    try:
        banner_name = BannerName(requested_file.stem)
        user_locale = Locale(locale)
        BannerFormat(requested_file.suffix.lstrip(".").lower())
    except ValueError:
        logger.warning(f"Invalid banner request: locale '{locale}', filename '{filename}'")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    try:
        banner_path, _ = get_banner(
            banners_dir=config.banners_dir,
            default_banners_dir=config.default_banners_dir,
            name=banner_name,
            locale=user_locale,
            default_locale=config.default_locale,
        )
    except FileNotFoundError:
        logger.warning(f"Banner '{banner_name}' not found for locale '{user_locale}'")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    return FileResponse(banner_path)
