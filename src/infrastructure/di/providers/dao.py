from dishka import Provider, Scope, provide

from src.application.common.dao import (
    AdLinkDao,
    AuthSessionDao,
    AuthTokenDao,
    BroadcastDao,
    DeviceSessionDao,
    LinkedDeviceDao,
    PaymentGatewayDao,
    PlanDao,
    PromocodeDao,
    RecentActivityDao,
    ReferralDao,
    SettingsDao,
    SubscriptionDao,
    TransactionDao,
    TvPairingDao,
    UserDao,
    UserOAuthProviderDao,
    WaitlistDao,
    WebhookDao,
)
from src.infrastructure.database.dao import (
    AdLinkDaoImpl,
    AuthTokenDaoImpl,
    BroadcastDaoImpl,
    DeviceSessionDaoImpl,
    LinkedDeviceDaoImpl,
    PaymentGatewayDaoImpl,
    PlanDaoImpl,
    PromocodeDaoImpl,
    ReferralDaoImpl,
    SettingsDaoImpl,
    SubscriptionDaoImpl,
    TransactionDaoImpl,
    TvPairingDaoImpl,
    UserDaoImpl,
    UserOAuthProviderDaoImpl,
    WaitlistDaoImpl,
    WebhookDaoImpl,
)
from src.infrastructure.redis.activity import RedisActivityRepository
from src.infrastructure.redis.auth import RedisAuthRepository


class DaoProvider(Provider):
    scope = Scope.REQUEST

    auth_token = provide(source=AuthTokenDaoImpl, provides=AuthTokenDao)
    ad_link = provide(source=AdLinkDaoImpl, provides=AdLinkDao)
    broadcast = provide(source=BroadcastDaoImpl, provides=BroadcastDao)
    device_session = provide(source=DeviceSessionDaoImpl, provides=DeviceSessionDao)
    linked_device = provide(source=LinkedDeviceDaoImpl, provides=LinkedDeviceDao)
    payment_gateway = provide(source=PaymentGatewayDaoImpl, provides=PaymentGatewayDao)
    plan = provide(source=PlanDaoImpl, provides=PlanDao)
    promocode = provide(source=PromocodeDaoImpl, provides=PromocodeDao)
    referral = provide(source=ReferralDaoImpl, provides=ReferralDao)
    settings = provide(source=SettingsDaoImpl, provides=SettingsDao)
    subscription = provide(source=SubscriptionDaoImpl, provides=SubscriptionDao)
    transaction = provide(source=TransactionDaoImpl, provides=TransactionDao)
    tv_pairing = provide(source=TvPairingDaoImpl, provides=TvPairingDao)
    user = provide(source=UserDaoImpl, provides=UserDao)
    oauth_provider = provide(source=UserOAuthProviderDaoImpl, provides=UserOAuthProviderDao)

    webhook = provide(source=WebhookDaoImpl, provides=WebhookDao, scope=Scope.APP)
    waitlist = provide(source=WaitlistDaoImpl, provides=WaitlistDao, scope=Scope.APP)
    auth_session = provide(source=RedisAuthRepository, provides=AuthSessionDao, scope=Scope.APP)
    recent_activity = provide(
        source=RedisActivityRepository, provides=RecentActivityDao, scope=Scope.APP
    )
