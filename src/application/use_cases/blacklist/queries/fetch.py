import aiohttp
from loguru import logger

from src.application.common import Interactor
from src.application.dto import UserDto
from src.core.utils.validators import parse_int


class FetchBlacklistIds(Interactor[str, list[int]]):
    required_permission = None

    async def _execute(self, actor: UserDto, url: str) -> list[int]:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status != 200:
                        logger.error(f"Failed to fetch blacklist '{url}': HTTP {resp.status}")
                        return []
                    text = await resp.text()
        except Exception as exc:
            logger.error(f"Failed to fetch blacklist '{url}': {exc}")
            return []

        return _parse_ids(text)


class ParseBlacklistIds(Interactor[str, list[int]]):
    required_permission = None

    async def _execute(self, actor: UserDto, text: str) -> list[int]:
        return _parse_ids(text)


def _parse_ids(text: str) -> list[int]:
    ids: list[int] = []
    for line in text.splitlines():
        token = line.strip().split()[0].rstrip(",;") if line.strip() else ""
        parsed = parse_int(token)
        if parsed is not None:
            ids.append(parsed)
    return ids
