from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from src.infrastructure.database.dao.subscription import SubscriptionDaoImpl
from src.infrastructure.database.dao.user import UserDaoImpl
from src.infrastructure.database.models import User


def test_registration_filter_keeps_only_accounts_not_older_than_period() -> None:
    stmt = UserDaoImpl._filter_broadcast_recipients(
        select(User),
        excluded_telegram_ids=[],
        exclude_registered_older_than_days=7,
    )

    sql = str(stmt.compile(dialect=postgresql.dialect()))

    assert "users.created_at >=" in sql
    assert "users.created_at <" not in sql


def test_registration_filter_is_not_applied_to_regular_statistics() -> None:
    stmt = UserDaoImpl._filter_broadcast_recipients(
        select(User),
        excluded_telegram_ids=None,
        exclude_registered_older_than_days=None,
    )

    sql = str(stmt.compile(dialect=postgresql.dialect()))

    assert "\nWHERE " not in sql


async def test_plan_audience_uses_the_same_registration_age_semantics() -> None:
    class _Result:
        def scalar(self) -> int:
            return 0

    class _Session:
        stmt = None

        async def execute(self, stmt):
            self.stmt = stmt
            return _Result()

    session = _Session()
    dao = SubscriptionDaoImpl.__new__(SubscriptionDaoImpl)
    dao.session = session

    await dao.count_active_by_plan(
        plan_id=1,
        excluded_telegram_ids=[],
        exclude_registered_older_than_days=30,
    )
    sql = str(session.stmt.compile(dialect=postgresql.dialect()))

    assert "users.created_at >=" in sql
    assert "users.created_at <" not in sql
