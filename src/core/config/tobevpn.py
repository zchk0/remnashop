from pydantic import field_validator

from .base import BaseConfig


class ToBeVpnConfig(BaseConfig, env_prefix="TOBEVPN_"):
    enabled: bool = False
    access_token_ttl_seconds: int = 1800
    refresh_token_ttl_seconds: int = 7776000
    auth_request_ttl_seconds: int = 86400
    anonymous_trial_traffic_gb: int = 0

    @property
    def is_enabled(self) -> bool:
        return self.enabled

    @field_validator("anonymous_trial_traffic_gb")
    @classmethod
    def validate_anonymous_trial_traffic_gb(cls, field: int) -> int:
        if field < 0:
            raise ValueError(
                "TOBEVPN_ANONYMOUS_TRIAL_TRAFFIC_GB must be greater than or equal to 0"
            )
        return field
