from pydantic import BaseModel, Field, SecretStr, ValidationError, field_validator
from pydantic_settings import SettingsConfigDict

from .base import BaseConfig


class FcmServiceAccount(BaseModel):
    project_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,63}$")
    client_email: str = Field(min_length=1)
    private_key: SecretStr
    private_key_id: str | None = None


class ToBeVpnConfig(BaseConfig, env_prefix="TOBEVPN_"):
    model_config = SettingsConfigDict(hide_input_in_errors=True)

    enabled: bool = False
    access_token_ttl_seconds: int = 1800
    refresh_token_ttl_seconds: int = 7776000
    auth_request_ttl_seconds: int = 86400
    anonymous_trial_traffic_gb: int = 0
    fcm_service_account_json: SecretStr | None = None

    @property
    def is_enabled(self) -> bool:
        return self.enabled

    @field_validator("fcm_service_account_json")
    @classmethod
    def validate_fcm_account(cls, value: SecretStr | None) -> SecretStr | None:
        if value is None or not value.get_secret_value().strip():
            return None
        try:
            FcmServiceAccount.model_validate_json(value.get_secret_value())
        except ValidationError:
            raise ValueError("TOBEVPN_FCM_SERVICE_ACCOUNT_JSON is invalid") from None
        return value

    @field_validator("anonymous_trial_traffic_gb")
    @classmethod
    def validate_anonymous_trial_traffic_gb(cls, field: int) -> int:
        if field < 0:
            raise ValueError(
                "TOBEVPN_ANONYMOUS_TRIAL_TRAFFIC_GB must be greater than or equal to 0"
            )
        return field
