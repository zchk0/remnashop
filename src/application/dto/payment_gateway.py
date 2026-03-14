from dataclasses import dataclass, fields
from typing import Any, Literal, Optional, Union
from uuid import UUID

from pydantic import SecretStr

from src.core.enums import Currency, PaymentGatewayType, YookassaVatCode

from .base import BaseDto, TrackableMixin


@dataclass(kw_only=True)
class PaymentResultDto:
    id: UUID
    url: Optional[str] = None


@dataclass(kw_only=True)
class PaymentGatewayDto(BaseDto, TrackableMixin):
    order_index: int = 0
    type: PaymentGatewayType
    currency: Currency

    is_active: bool = False
    settings: Optional["AnyGatewaySettingsDto"] = None

    @property
    def requires_webhook(self) -> bool:
        return self.type not in {
            PaymentGatewayType.CRYPTOMUS,
            PaymentGatewayType.HELEKET,
            PaymentGatewayType.FREEKASSA,
            PaymentGatewayType.PAYMASTER,
            PaymentGatewayType.PLATEGA,
        }


@dataclass(kw_only=True)
class GatewaySettingsDto(TrackableMixin):
    @property
    def is_configured(self) -> bool:
        for f in fields(self):
            if f.name in {"created_at", "updated_at", "type"}:
                continue
            if getattr(self, f.name) is None:
                return False
        return True

    @property
    def as_list(self) -> list[dict[str, Any]]:
        return [
            {"field": f.name, "value": getattr(self, f.name)}
            for f in fields(self)
            if f.name not in {"type", "created_at", "updated_at"} and not f.name.startswith("_")
        ]


@dataclass(kw_only=True)
class YookassaGatewaySettingsDto(GatewaySettingsDto):
    type: Literal[PaymentGatewayType.YOOKASSA] = PaymentGatewayType.YOOKASSA
    shop_id: Optional[int] = None
    api_key: Optional[SecretStr] = None
    customer: Optional[str] = None
    vat_code: Optional[YookassaVatCode] = None


@dataclass(kw_only=True)
class YoomoneyGatewaySettingsDto(GatewaySettingsDto):
    type: Literal[PaymentGatewayType.YOOMONEY] = PaymentGatewayType.YOOMONEY
    wallet_id: Optional[str] = None
    secret_key: Optional[SecretStr] = None


@dataclass(kw_only=True)
class CryptomusGatewaySettingsDto(GatewaySettingsDto):
    type: Literal[PaymentGatewayType.CRYPTOMUS] = PaymentGatewayType.CRYPTOMUS
    merchant_id: Optional[str] = None
    api_key: Optional[SecretStr] = None


@dataclass(kw_only=True)
class HeleketGatewaySettingsDto(GatewaySettingsDto):
    type: Literal[PaymentGatewayType.HELEKET] = PaymentGatewayType.HELEKET
    merchant_id: Optional[str] = None
    api_key: Optional[SecretStr] = None


@dataclass(kw_only=True)
class CryptopayGatewaySettingsDto(GatewaySettingsDto):
    type: Literal[PaymentGatewayType.CRYPTOPAY] = PaymentGatewayType.CRYPTOPAY
    shop_id: Optional[str] = None
    api_key: Optional[SecretStr] = None
    secret_key: Optional[SecretStr] = None


@dataclass(kw_only=True)
class FreeKassaGatewaySettingsDto(GatewaySettingsDto):
    type: Literal[PaymentGatewayType.FREEKASSA] = PaymentGatewayType.FREEKASSA
    shop_id: Optional[int] = None
    api_key: Optional[SecretStr] = None  # API-ключ из ЛК
    secret_word_2: Optional[SecretStr] = None  # Секретное слово 2 (для проверки вебхука)
    payment_system_id: Optional[int] = None  # ID платёжной системы (например, 4 = VISA RUB)
    customer_email: Optional[str] = None  # Email покупателя (обязателен для API)
    customer_ip: Optional[str] = None  # IP покупателя (обязателен для API)


@dataclass(kw_only=True)
class MulenPayGatewaySettingsDto(GatewaySettingsDto):
    type: Literal[PaymentGatewayType.MULENPAY] = PaymentGatewayType.MULENPAY
    api_key: Optional[SecretStr] = None  # Bearer-токен из ЛК
    secret_key: Optional[SecretStr] = None  # Секретный ключ для подписи
    shop_id: Optional[int] = None  # ID магазина из ЛК
    vat_code: Optional[int] = None  # Код НДС (0 = без НДС)


@dataclass(kw_only=True)
class PayMasterGatewaySettingsDto(GatewaySettingsDto):
    type: Literal[PaymentGatewayType.PAYMASTER] = PaymentGatewayType.PAYMASTER
    merchant_id: Optional[str] = None  # UUID магазина из личного кабинета
    api_key: Optional[SecretStr] = None  # Bearer-токен из личного кабинета


@dataclass(kw_only=True)
class PlategaGatewaySettingsDto(GatewaySettingsDto):
    type: Literal[PaymentGatewayType.PLATEGA] = PaymentGatewayType.PLATEGA
    merchant_id: Optional[str] = None  # X-MerchantId из ЛК
    api_key: Optional[SecretStr] = None  # X-Secret из ЛК
    payment_method: Optional[int] = None  # ID платёжного метода (например, 2 = СБП)


@dataclass(kw_only=True)
class RobokassaGatewaySettingsDto(GatewaySettingsDto):
    type: Literal[PaymentGatewayType.ROBOKASSA] = PaymentGatewayType.ROBOKASSA
    merchant_login: Optional[str] = None  # Логин магазина из ЛК
    password1: Optional[SecretStr] = None  # Пароль №1 (для создания платежа)
    password2: Optional[SecretStr] = None  # Пароль №2 (для проверки вебхука)
    hash_algorithm: Optional[str] = "md5"  # md5 / sha256 / sha384 / sha512


@dataclass(kw_only=True)
class UrlPayGatewaySettingsDto(GatewaySettingsDto):
    type: Literal[PaymentGatewayType.URLPAY] = PaymentGatewayType.URLPAY
    shop_id: Optional[int] = None  # ID магазина из ЛК
    api_key: Optional[SecretStr] = None  # Bearer-токен из ЛК
    secret_key: Optional[SecretStr] = None  # Секретный ключ для подписи
    vat_code: Optional[int] = None  # Код НДС (0 = без НДС)


@dataclass(kw_only=True)
class WataGatewaySettingsDto(GatewaySettingsDto):
    type: Literal[PaymentGatewayType.WATA] = PaymentGatewayType.WATA
    api_key: Optional[SecretStr] = None  # Bearer access token из ЛК (терминал → токены)


AnyGatewaySettingsDto = Union[
    YookassaGatewaySettingsDto,
    YoomoneyGatewaySettingsDto,
    CryptomusGatewaySettingsDto,
    HeleketGatewaySettingsDto,
    CryptopayGatewaySettingsDto,
    FreeKassaGatewaySettingsDto,
    MulenPayGatewaySettingsDto,
    PayMasterGatewaySettingsDto,
    PlategaGatewaySettingsDto,
    RobokassaGatewaySettingsDto,
    UrlPayGatewaySettingsDto,
    WataGatewaySettingsDto,
]
