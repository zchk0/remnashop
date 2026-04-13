import re
from pathlib import Path
from typing import Self

from pydantic import Field, SecretStr, field_validator
from pydantic_core.core_schema import FieldValidationInfo

from src.core.constants import (
    API_V1,
    ASSETS_DIR,
    DOMAIN_REGEX,
    PAYMENTS_WEBHOOK_PATH,
    TELEGRAM_WEBHOOK_DOMAIN_REGEX,
)
from src.core.enums import Locale, PaymentGatewayType
from src.core.types import LocaleList, StringList

from .base import BaseConfig
from .bot import BotConfig
from .build import BuildConfig
from .database import DatabaseConfig
from .log import LogConfig
from .redis import RedisConfig
from .remnawave import RemnawaveConfig
from .validators import validate_not_change_me


class AppConfig(BaseConfig, env_prefix="APP_"):
    domain: SecretStr
    telegram_webhook_domain: SecretStr | None = Field(
        default=None,
        validation_alias="TELEGRAM_WEBHOOK_DOMAIN",
    )
    host: str = "0.0.0.0"
    port: int = 5000

    locales: LocaleList = LocaleList([Locale.RU])  # TODO: Change to EN
    default_locale: Locale = Locale.RU  # TODO: Change to EN

    crypt_key: SecretStr
    assets_dir: Path = ASSETS_DIR
    origins: StringList = StringList("")

    bot: BotConfig = Field(default_factory=BotConfig)
    remnawave: RemnawaveConfig = Field(default_factory=RemnawaveConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    redis: RedisConfig = Field(default_factory=RedisConfig)
    build: BuildConfig = Field(default_factory=BuildConfig)
    log: LogConfig = Field(default_factory=LogConfig)

    @property
    def banners_dir(self) -> Path:
        return self.assets_dir / "banners"

    @property
    def translations_dir(self) -> Path:
        return self.assets_dir / "translations"

    @property
    def bot_webhook_domain(self) -> SecretStr:
        return self.telegram_webhook_domain or self.domain

    def get_webhook(self, gateway_type: PaymentGatewayType) -> str:
        domain = f"https://{self.domain.get_secret_value()}"
        path = f"{API_V1 + PAYMENTS_WEBHOOK_PATH}/{gateway_type.lower()}"
        return domain + path

    @classmethod
    def get(cls) -> Self:
        return cls()

    @field_validator("domain")
    @classmethod
    def validate_domain(cls, field: SecretStr, info: FieldValidationInfo) -> SecretStr:
        validate_not_change_me(field, info)

        if not re.match(DOMAIN_REGEX, field.get_secret_value()):
            raise ValueError("APP_DOMAIN has invalid format")

        return field

    @field_validator("telegram_webhook_domain", mode="before")
    @classmethod
    def normalize_telegram_webhook_domain(cls, field: object) -> object:
        if isinstance(field, SecretStr):
            value = field.get_secret_value().strip()
            return SecretStr(value) if value else None

        if isinstance(field, str):
            value = field.strip()
            return value or None

        return field

    @field_validator("telegram_webhook_domain")
    @classmethod
    def validate_telegram_webhook_domain(
        cls,
        field: SecretStr | None,
    ) -> SecretStr | None:
        if field is None:
            return field

        value = field.get_secret_value()
        if value.lower() == "change_me":
            raise ValueError("TELEGRAM_WEBHOOK_DOMAIN must be set and not equal to 'change_me'")

        if not re.match(TELEGRAM_WEBHOOK_DOMAIN_REGEX, value):
            raise ValueError(
                "TELEGRAM_WEBHOOK_DOMAIN must be a domain without scheme/trailing slash "
                "and may include only ports 80, 88, 443 or 8443"
            )

        return field

    @field_validator("crypt_key")
    @classmethod
    def validate_crypt_key(cls, field: SecretStr, info: FieldValidationInfo) -> SecretStr:
        validate_not_change_me(field, info)

        if not re.match(r"^[A-Za-z0-9+/=]{44}$", field.get_secret_value()):
            raise ValueError("APP_CRYPT_KEY must be a valid 44-character Base64 string")

        return field
