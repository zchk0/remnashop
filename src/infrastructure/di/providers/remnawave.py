from collections.abc import AsyncIterator

from dishka import Provider, Scope, provide
from httpx import AsyncClient, Timeout
from loguru import logger
from remnapy import RemnawaveSDK

from src.core.config import AppConfig
from src.infrastructure.remnawave_v3.client import RemnawaveV3Client
from src.infrastructure.remnawave_v3.compat import PanelClient


class RemnawaveProvider(Provider):
    scope = Scope.APP

    @provide
    def get_panel_client(self, sdk: RemnawaveSDK, config: AppConfig) -> PanelClient:
        assert sdk._client is not None
        return PanelClient(sdk, RemnawaveV3Client(sdk._client), config.remnawave.api_version)

    @provide
    async def get_remnawave(self, config: AppConfig) -> AsyncIterator[RemnawaveSDK]:
        logger.debug("Initializing RemnawaveSDK")

        headers = {}
        headers["Authorization"] = f"Bearer {config.remnawave.token.get_secret_value()}"
        headers["X-Api-Key"] = config.remnawave.caddy_token.get_secret_value()
        headers["CF-Access-Client-Id"] = config.remnawave.cf_client_id.get_secret_value()
        headers["CF-Access-Client-Secret"] = config.remnawave.cf_client_secret.get_secret_value()

        if not config.remnawave.is_external:
            headers["x-forwarded-proto"] = "https"
            headers["x-forwarded-for"] = "127.0.0.1"

        client = AsyncClient(
            base_url=f"{config.remnawave.url.get_secret_value()}/api",
            headers=headers,
            cookies=config.remnawave.cookies,
            verify=True,
            timeout=Timeout(connect=15.0, read=25.0, write=10.0, pool=5.0),
        )

        try:
            yield RemnawaveSDK(client)
        finally:
            await client.aclose()
            logger.debug("RemnawaveSDK AsyncClient closed")
