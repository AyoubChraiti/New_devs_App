import unittest
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.api.v1.dashboard import get_current_user, router
from app.core.database_pool import DatabasePool
from app.services import cache, reservations


class RevenueDatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def test_query_returns_database_amount_and_count(self):
        for amount, count in [(Decimal('2250.000'), 4), (Decimal('0'), 0)]:
            with self.subTest(count=count):
                pool = MagicMock()
                pool.initialize = AsyncMock()
                session = AsyncMock()
                pool.get_session.return_value.__aenter__.return_value = session
                result = MagicMock()
                result.one.return_value = SimpleNamespace(total_revenue=amount, reservation_count=count)
                session.execute.return_value = result
                with patch.object(reservations, 'db_pool', pool):
                    actual = await reservations.calculate_total_revenue('prop-001', 'tenant-a')
                self.assertEqual(Decimal(actual['total']), amount)
                self.assertEqual(actual['count'], count)
                self.assertEqual(session.execute.call_args.args[1],
                                 {'property_id': 'prop-001', 'tenant_id': 'tenant-a'})
                pool.get_session.return_value.__aexit__.assert_awaited_once()

    async def test_database_failure_propagates_and_is_not_cached(self):
        for stage in ['initialize', 'query']:
            with self.subTest(stage=stage):
                pool = MagicMock()
                pool.initialize = AsyncMock()
                session = AsyncMock()
                pool.get_session.return_value.__aenter__.return_value = session
                failure = OperationalError('SELECT', {}, Exception('database unavailable'))
                if stage == 'initialize':
                    pool.initialize.side_effect = failure
                else:
                    session.execute.side_effect = failure
                redis = AsyncMock()
                redis.get.return_value = None
                with patch.object(reservations, 'db_pool', pool), patch.object(cache, 'redis_client', redis):
                    with self.assertLogs('app.services.reservations', level='ERROR'):
                        with self.assertRaises(reservations.RevenueUnavailableError):
                            await cache.get_revenue_summary('prop-001', 'tenant-a')
                redis.setex.assert_not_awaited()

    async def test_pool_reuses_engine_and_releases_it_on_close(self):
        pool = DatabasePool()
        try:
            await pool.initialize()
            engine = pool.engine
            self.assertEqual(engine.url.drivername, 'postgresql+asyncpg')
            await pool.initialize()
            self.assertIs(pool.engine, engine)
            async with pool.get_session() as session:
                self.assertIs(session.bind, engine)
        finally:
            await pool.close()
        self.assertIsNone(pool.engine)
        self.assertIsNone(pool.session_factory)

    async def test_old_mock_cache_is_bypassed(self):
        redis = AsyncMock()
        redis.get.side_effect = lambda key: b'{"tenant_id":"tenant-a","property_id":"prop-001","total":"1000.00"}' if key.startswith('revenue:v2:') else None
        with patch.object(cache, 'redis_client', redis), patch.object(
            reservations, 'calculate_total_revenue', new_callable=AsyncMock,
            return_value={'tenant_id': 'tenant-a', 'property_id': 'prop-001', 'total': '2250.000'},
        ) as calculate:
            result = await cache.get_revenue_summary('prop-001', 'tenant-a')
        self.assertEqual(result['total'], '2250.000')
        calculate.assert_awaited_once()


class RevenueFailureResponseTests(unittest.TestCase):
    def test_database_failure_returns_503_without_internal_details(self):
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(tenant_id='tenant-a')
        with patch('app.api.v1.dashboard.get_tenant_properties', new_callable=AsyncMock, return_value=[{'id': 'prop-001'}]), patch('app.api.v1.dashboard.get_revenue_summary', new_callable=AsyncMock,
                   side_effect=reservations.RevenueUnavailableError('private database details')):
            with TestClient(app) as client:
                response = client.get('/dashboard/summary?property_id=prop-001')
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {'detail': 'Revenue is temporarily unavailable'})
