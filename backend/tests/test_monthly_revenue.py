import json
import os
import unittest
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.api.v1.dashboard import router, get_current_user
from app.core.database_pool import DatabasePool
from app.services import reservations, cache


class MonthBoundsTests(unittest.TestCase):
    def test_dst_and_year_boundaries(self):
        cases = [
            (2024, 3, 'Europe/Paris', '2024-02-29T23:00:00+00:00', '2024-03-31T22:00:00+00:00'),
            (2024, 3, 'America/New_York', '2024-03-01T05:00:00+00:00', '2024-04-01T04:00:00+00:00'),
            (2024, 10, 'Europe/Paris', '2024-09-30T22:00:00+00:00', '2024-10-31T23:00:00+00:00'),
            (2024, 11, 'America/New_York', '2024-11-01T04:00:00+00:00', '2024-12-01T05:00:00+00:00'),
            (2024, 12, 'UTC', '2024-12-01T00:00:00+00:00', '2025-01-01T00:00:00+00:00'),
            (2024, 2, 'UTC', '2024-02-01T00:00:00+00:00', '2024-03-01T00:00:00+00:00'),
        ]
        for year, month, zone, start, end in cases:
            with self.subTest(zone=zone, month=month):
                actual = reservations.monthly_utc_bounds(year, month, zone)
                self.assertEqual(tuple(value.isoformat() for value in actual), (start, end))


class MonthlyEndpointTests(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(tenant_id='tenant-a')
        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    def test_invalid_and_incomplete_periods_are_rejected(self):
        for query in ['month=3', 'year=2024', 'month=0&year=2024', 'month=13&year=2024',
                      'month=3&year=0', 'month=3&year=9999', 'month=abc&year=2024']:
            self.assertEqual(self.client.get('/dashboard/summary?property_id=prop-001&' + query).status_code, 422)

    def test_timezone_is_taken_from_owned_property(self):
        with patch('app.api.v1.dashboard.get_tenant_properties', new_callable=AsyncMock,
                   return_value=[{'id': 'prop-001', 'timezone': 'Europe/Paris'}]), patch(
            'app.api.v1.dashboard.get_revenue_summary', new_callable=AsyncMock,
            return_value={'property_id': 'prop-001', 'total': '2250', 'currency': 'USD', 'count': 4},
        ) as fetch:
            response = self.client.get('/dashboard/summary?property_id=prop-001&month=3&year=2024&timezone=UTC')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['timezone'], 'Europe/Paris')
            fetch.assert_awaited_once_with('prop-001', 'tenant-a', month=3, year=2024, timezone_name='Europe/Paris')


class MonthlyCacheTests(unittest.IsolatedAsyncioTestCase):
    async def test_periods_years_timezones_and_all_time_do_not_collide(self):
        entries = {}
        redis = AsyncMock()
        redis.get.side_effect = entries.get
        async def put(key, ttl, value):
            entries[key] = value
        redis.setex.side_effect = put
        def monthly(prop, tenant, month, year, zone):
            return dict(property_id=prop, tenant_id=tenant, total=str(month), count=1,
                        currency='USD', month=month, year=year, timezone=zone)
        with patch.object(cache, 'redis_client', redis), patch.object(
            reservations, 'calculate_monthly_revenue', new_callable=AsyncMock, side_effect=monthly
        ) as calculate, patch.object(reservations, 'calculate_total_revenue', new_callable=AsyncMock,
                                    return_value={'property_id': 'prop-001', 'tenant_id': 'tenant-a', 'total': '100'}):
            for _ in range(2):
                for month, year, zone in [(3, 2024, 'Europe/Paris'), (4, 2024, 'Europe/Paris'),
                                          (3, 2025, 'Europe/Paris'), (3, 2024, 'America/New_York')]:
                    result = await cache.get_revenue_summary('prop-001', 'tenant-a', month=month, year=year, timezone_name=zone)
                    self.assertEqual((result['month'], result['year'], result['timezone']), (month, year, zone))
                await cache.get_revenue_summary('prop-001', 'tenant-a')
            self.assertEqual(calculate.await_count, 4)
            self.assertEqual(len(entries), 5)
            key = next(iter(entries))
            wrong = json.loads(entries[key])
            wrong['month'] = 12
            entries[key] = json.dumps(wrong)
            result = await cache.get_revenue_summary('prop-001', 'tenant-a', month=3, year=2024, timezone_name='Europe/Paris')
            self.assertEqual(result['month'], 3)
            self.assertEqual(calculate.await_count, 5)

    async def test_invalid_property_timezone_fails_honestly(self):
        with self.assertRaises(reservations.RevenueUnavailableError):
            await reservations.calculate_monthly_revenue('prop-001', 'tenant-a', 3, 2024, 'Invalid/Zone')


@unittest.skipUnless(os.getenv('RUN_DB_TESTS') == '1', 'Requires development PostgreSQL')
class MonthlyPostgresTests(unittest.IsolatedAsyncioTestCase):
    async def test_half_open_boundaries_and_tenant_isolation_in_postgres(self):
        pool = DatabasePool()
        await pool.initialize()
        try:
            async with pool.get_session() as session:
                # This connection-local table shadows the real table; no fixture data is changed.
                await session.execute(text('CREATE TEMP TABLE reservations (property_id TEXT, tenant_id TEXT, check_in_date TIMESTAMPTZ, total_amount NUMERIC(10,3))'))
                rows = [
                    ('tenant-a', '2024-02-29T22:59:59+00:00', '10'),
                    ('tenant-a', '2024-02-29T23:00:00+00:00', '20'),
                    ('tenant-a', '2024-02-29T23:30:00+00:00', '1250'),
                    ('tenant-a', '2024-03-31T21:59:59+00:00', '30'),
                    ('tenant-a', '2024-03-31T22:00:00+00:00', '40'),
                    ('tenant-b', '2024-03-15T10:00:00+00:00', '999'),
                ]
                for tenant, date, amount in rows:
                    await session.execute(text("INSERT INTO reservations VALUES ('prop-001', :tenant, :date, :amount)"),
                                          dict(tenant=tenant, date=datetime.fromisoformat(date), amount=float(amount)))
                @asynccontextmanager
                async def same_session():
                    yield session
                scoped_pool = SimpleNamespace(initialize=AsyncMock(), get_session=same_session)
                with patch.object(reservations, 'db_pool', scoped_pool):
                    result = await reservations.calculate_monthly_revenue('prop-001', 'tenant-a', 3, 2024, 'Europe/Paris')
                    self.assertEqual(result['total'], '1300.000')
                    self.assertEqual(result['count'], 3)
                    empty = await reservations.calculate_monthly_revenue('prop-001', 'tenant-a', 5, 2024, 'Europe/Paris')
                    self.assertEqual(empty['count'], 0)
                await session.rollback()
        finally:
            await pool.close()
