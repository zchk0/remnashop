from pydantic import SecretStr, field_validator

from .base import BaseConfig


class ToBeVpnConfig(BaseConfig, env_prefix="TOBEVPN_"):
    without_legacy_support: bool = False
    api_token: SecretStr = SecretStr("")
    access_token_ttl_seconds: int = 1800
    refresh_token_ttl_seconds: int = 7776000
    auth_request_ttl_seconds: int = 86400
    anonymous_trial_traffic_gb: int = 0

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

    @field_validator("anonymous_trial_traffic_gb")
    @classmethod
    def validate_anonymous_trial_traffic_gb(cls, field: int) -> int:
        if field < 0:
            raise ValueError("TOBEVPN_ANONYMOUS_TRIAL_TRAFFIC_GB must be greater than or equal to 0")
        return field
