from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class ReferralRewardLevelResponse(BaseModel):
    level: int
    value: int


class ReferralProgramResponse(BaseModel):
    enabled: bool
    referral_code: str
    invited_count: int
    invited_with_payment_count: int
    reward_type: str
    reward_strategy: str
    accrual_strategy: str
    max_level: int
    reward_levels: list[ReferralRewardLevelResponse]


class ToBeVpnReferralUserResponse(BaseModel):
    telegram_id: Optional[int]
    display_name: str


class ToBeVpnReferralListItemResponse(ToBeVpnReferralUserResponse):
    level: int
    created_at: Optional[datetime]


class ToBeVpnReferralDataResponse(BaseModel):
    referral_code: str
    referral_url: str
    referrer: Optional[ToBeVpnReferralUserResponse]
    total: int
    referals: list[ToBeVpnReferralListItemResponse]
    limit: int
    offset: int


class ToBeVpnReferralsResponse(BaseModel):
    success: bool = True
    data: ToBeVpnReferralDataResponse
