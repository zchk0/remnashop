from pydantic import SecretStr, field_validator

from .base import BaseConfig


class ToBeVpnConfig(BaseConfig, env_prefix="TOBEVPN_"):
    api_token: SecretStr = SecretStr("")

    @property
    def is_enabled(self) -> bool:
        return bool(self.api_token.get_secret_value())

    @field_validator("api_token")
    @classmethod
    def validate_api_token(cls, field: SecretStr) -> SecretStr:
        token = field.get_secret_value().strip()
        if token.lower() == "change_me":
            return SecretStr("")
        return SecretStr(token)
