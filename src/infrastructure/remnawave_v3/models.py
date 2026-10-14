"""Models for the user/HWID subset of @remnawave/backend-contract 3.4.5."""

from datetime import datetime
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, EmailStr, Field, model_validator
from pydantic.alias_generators import to_camel

UserId = Annotated[int, Field(strict=True, gt=0)]
NonNegativeInt = Annotated[int, Field(ge=0)]
UserStatus = Literal["ACTIVE", "DISABLED", "LIMITED", "EXPIRED"]
TrafficStrategy = Literal["NO_RESET", "DAY", "WEEK", "MONTH", "MONTH_ROLLING"]


class ResponseModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="ignore")


class RequestModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")


class UserWriteFields(RequestModel):
    traffic_limit_bytes: NonNegativeInt | None = None
    traffic_limit_strategy: TrafficStrategy | None = None
    hwid_device_limit: NonNegativeInt | None = None
    description: str | None = None
    tag: Annotated[str, Field(pattern=r"^[A-Z0-9_]+$", max_length=16)] | None = None
    telegram_id: int | None = None
    email: EmailStr | None = None
    active_internal_squads: list[UUID] | None = None
    external_squad_uuid: UUID | None = None

    @model_validator(mode="after")
    def reject_null_nonnullable_fields(self) -> Self:
        for name in ("traffic_limit_bytes", "traffic_limit_strategy", "active_internal_squads"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} may be omitted, but cannot be null")
        return self


class CreateUser(RequestModel):
    username: Annotated[str, Field(pattern=r"^[a-zA-Z0-9_-]+$", min_length=3, max_length=36)]
    expire_at: AwareDatetime
    created_at: AwareDatetime | None = None
    last_traffic_reset_at: AwareDatetime | None = None
    status: UserStatus = "ACTIVE"
    traffic_limit_bytes: NonNegativeInt = 0
    traffic_limit_strategy: TrafficStrategy = "NO_RESET"
    hwid_device_limit: NonNegativeInt = 0
    description: str = ""
    tag: Annotated[str, Field(pattern=r"^[A-Z0-9_]+$", max_length=16)] | None = None
    telegram_id: int | None = None
    email: EmailStr | None = None
    active_internal_squads: list[UUID] = Field(default_factory=list)
    external_squad_uuid: UUID | None = None
    short_uuid: str | None = None
    vless_uuid: UUID | None = Field(default=None, repr=False)
    trojan_password: Annotated[str, Field(min_length=8, max_length=32)] | None = Field(
        default=None, repr=False
    )
    ss_password: Annotated[str, Field(min_length=8, max_length=32)] | None = Field(
        default=None, repr=False
    )

    @model_validator(mode="after")
    def reject_null_credentials(self) -> Self:
        for name in (
            "short_uuid",
            "vless_uuid",
            "trojan_password",
            "ss_password",
            "created_at",
            "last_traffic_reset_at",
        ):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} may be omitted, but cannot be null")
        return self


class UpdateUser(UserWriteFields):
    id: UserId
    expire_at: AwareDatetime | None = None
    status: Literal["ACTIVE", "DISABLED"] | None = None

    @model_validator(mode="after")
    def reject_null_subscription_fields(self) -> Self:
        for name in ("expire_at", "status"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} may be omitted, but cannot be null")
        return self


class UserTraffic(ResponseModel):
    used_traffic_bytes: NonNegativeInt
    lifetime_used_traffic_bytes: NonNegativeInt
    online_at: datetime | None = None
    first_connected_at: datetime | None = None
    last_connected_node_uuid: UUID | None = None


class InternalSquad(ResponseModel):
    uuid: UUID
    name: str


class User(ResponseModel):
    id: UserId
    short_uuid: str
    username: str
    status: UserStatus
    expire_at: datetime
    subscription_url: str
    traffic_limit_bytes: NonNegativeInt
    traffic_limit_strategy: TrafficStrategy
    user_traffic: UserTraffic
    created_at: datetime
    updated_at: datetime
    telegram_id: int | None = None
    email: str | None = None
    description: str | None = None
    tag: str | None = None
    hwid_device_limit: int | None = None
    external_squad_uuid: UUID | None = None
    active_internal_squads: list[InternalSquad] = Field(default_factory=list)
    last_traffic_reset_at: datetime | None = None

    @property
    def uuid(self) -> None:
        return None

    @property
    def used_traffic_bytes(self) -> int:
        return self.user_traffic.used_traffic_bytes

    @property
    def lifetime_used_traffic_bytes(self) -> int:
        return self.user_traffic.lifetime_used_traffic_bytes

    @property
    def online_at(self) -> datetime | None:
        return self.user_traffic.online_at

    @property
    def first_connected_at(self) -> datetime | None:
        return self.user_traffic.first_connected_at

    @property
    def last_connected_node_uuid(self) -> UUID | None:
        return self.user_traffic.last_connected_node_uuid


class UsersPage(ResponseModel):
    users: list[User]
    total: NonNegativeInt


class UsersStreamPage(ResponseModel):
    users: list[User]
    next_cursor: str | None
    has_more: Annotated[bool, Field(strict=True)]


class UserFilters(RequestModel):
    telegram_id: Annotated[int, Field(strict=True, ge=0)] | None = None
    email: EmailStr | None = None
    tag: str | None = None
    status: UserStatus | None = None
    traffic_limit_strategy: TrafficStrategy | None = None
    external_squad_uuid: UUID | None = None


class HwidDevice(ResponseModel):
    hwid: str
    user_id: UserId
    created_at: datetime
    updated_at: datetime
    platform: str | None = None
    os_version: str | None = None
    device_model: str | None = None
    user_agent: str | None = None
    request_ip: str | None = None


class HwidDevices(ResponseModel):
    total: NonNegativeInt
    devices: list[HwidDevice]


class Metadata(ResponseModel):
    version: str


class SubscriptionInfoUser(ResponseModel):
    short_uuid: str
    days_left: float
    traffic_used: str
    traffic_limit: str
    lifetime_traffic_used: str
    traffic_used_bytes: str
    traffic_limit_bytes: str
    lifetime_traffic_used_bytes: str
    username: str
    expires_at: datetime
    is_active: bool
    user_status: UserStatus
    traffic_limit_strategy: TrafficStrategy


class SubscriptionInfo(ResponseModel):
    is_found: bool
    user: SubscriptionInfoUser
    links: list[str]
    ss_conf_links: dict[str, str]
    subscription_url: str
