from dishka import Provider, Scope, provide

from src.application.common.dao import (
    AuthTokenDao,
    BroadcastDao,
    LinkedDeviceDao,
    PaymentGatewayDao,
    PlanDao,
    ReferralDao,
    SettingsDao,
    SubscriptionDao,
    TransactionDao,
    TvPairingDao,
    UserDao,
    WaitlistDao,
    WebhookDao,
)
from src.infrastructure.database.dao import (
    AuthTokenDaoImpl,
    BroadcastDaoImpl,
    LinkedDeviceDaoImpl,
    PaymentGatewayDaoImpl,
    PlanDaoImpl,
    ReferralDaoImpl,
    SettingsDaoImpl,
    SubscriptionDaoImpl,
    TransactionDaoImpl,
    TvPairingDaoImpl,
    UserDaoImpl,
    WaitlistDaoImpl,
    WebhookDaoImpl,
)


class DaoProvider(Provider):
    scope = Scope.REQUEST

    auth_token = provide(source=AuthTokenDaoImpl, provides=AuthTokenDao)
    broadcast = provide(source=BroadcastDaoImpl, provides=BroadcastDao)
    linked_device = provide(source=LinkedDeviceDaoImpl, provides=LinkedDeviceDao)
    payment_gateway = provide(source=PaymentGatewayDaoImpl, provides=PaymentGatewayDao)
    plan = provide(source=PlanDaoImpl, provides=PlanDao)
    referral = provide(source=ReferralDaoImpl, provides=ReferralDao)
    settings = provide(source=SettingsDaoImpl, provides=SettingsDao)
    subscription = provide(source=SubscriptionDaoImpl, provides=SubscriptionDao)
    transaction = provide(source=TransactionDaoImpl, provides=TransactionDao)
    tv_pairing = provide(source=TvPairingDaoImpl, provides=TvPairingDao)
    user = provide(source=UserDaoImpl, provides=UserDao)

    webhook = provide(source=WebhookDaoImpl, provides=WebhookDao, scope=Scope.APP)
    waitlist = provide(source=WaitlistDaoImpl, provides=WaitlistDao, scope=Scope.APP)
