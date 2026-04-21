from pydantic import SecretStr, field_validator

from .base import BaseConfig


class ToBeVpnConfig(BaseConfig, env_prefix="TOBEVPN_"):
    without_legacy_support: bool = False
    api_token: SecretStr = SecretStr("")
    access_token_ttl_seconds: int = 1800
    refresh_token_ttl_seconds: int = 7776000
    auth_request_ttl_seconds: int = 86400

    @property
    def is_enabled(self) -> bool:
        return self.without_legacy_support or self.has_legacy_api_token

    @property
    def has_legacy_api_token(self) -> bool:
        return bool(self.api_token.get_secret_value())

    @field_validator("api_token")
    @classmethod
    def validate_api_token(cls, field: SecretStr) -> SecretStr:
        token = field.get_secret_value().strip()
        if token.lower() == "change_me":
            return SecretStr("")
        return SecretStr(token)
