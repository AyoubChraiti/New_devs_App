import json
import os
import unittest
from contextlib import asynccontextmanager
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.api.v1.dashboard import router, get_current_user
from app.core.database_pool import DatabasePool
from app.services import reservations, cache


class MoneyTests(unittest.IsolatedAsyncioTestCase):
    async def calculate(self, rows):
        pool = MagicMock()
        pool.initialize = AsyncMock()
        session = AsyncMock()
        pool.get_session.return_value.__aenter__.return_value = session
        result = MagicMock()
        result.all.return_value = [SimpleNamespace(currency=code, total_revenue=Decimal(amount), reservation_count=count) for code, amount, count in rows]
        session.execute.return_value = result
        with patch.object(reservations, 'db_pool', pool):
            return await reservations.calculate_total_revenue('prop-001', 'tenant-a')

    async def test_currency_precision_rounding_and_exact_totals(self):
        result = await self.calculate([
            ('USD', '1000.000', 3), ('EUR', '2.675', 1), ('JPY', '1250.500', 1),
            ('KWD', '1.235', 1), ('GBP', '-2.675', 1), ('CAD', '-0.001', 1),
            ('CHF', '9007199254740993.015', 1),
        ])
        self.assertIsNone(result['total'])
        self.assertIsNone(result['currency'])
        self.assertEqual(result['count'], 9)
        totals = {row['currency']: row for row in result['revenue_by_currency']}
        for code, expected in [('USD','1000.00'), ('EUR','2.68'), ('JPY','1251'), ('KWD','1.235'),
                               ('GBP','-2.68'), ('CAD','0.00'), ('CHF','9007199254740993.02')]:
            self.assertEqual(totals[code]['total_revenue'], expected)
        self.assertEqual(totals['EUR']['exact_total_revenue'], '2.675')
        self.assertEqual(json.loads(json.dumps(result)), result)

    async def test_empty_results_do_not_invent_a_currency(self):
        result = await self.calculate([])
        self.assertEqual(result['revenue_by_currency'], [])
        self.assertEqual(result['count'], 0)
        self.assertIsNone(result['currency'])
        self.assertIsNone(result['total'])

    async def test_missing_or_unknown_currency_fails_honestly(self):
        for code in [None, '', 'usd', 'ZZZ']:
            with self.subTest(code=code), self.assertRaises(reservations.RevenueUnavailableError):
                await self.calculate([(code, '1.00', 1)])

    async def test_previous_currency_unsafe_cache_entries_are_bypassed(self):
        for month in [None, 3]:
            redis = AsyncMock()
            redis.get.side_effect = lambda key: None if key.startswith('revenue:v5:') else json.dumps({'tenant_id':'tenant-a','property_id':'prop-001','total':'999','currency':'USD'})
            expected = await self.calculate([('EUR','1.005',1)])
            method = 'calculate_total_revenue' if month is None else 'calculate_monthly_revenue'
            with patch.object(cache, 'redis_client', redis), patch.object(reservations, method, new_callable=AsyncMock, return_value=expected):
                options = {} if month is None else dict(month=3, year=2024, timezone_name='Europe/Paris')
                self.assertEqual(await cache.get_revenue_summary('prop-001','tenant-a',**options), expected)
                redis.setex.assert_awaited_once()


class MoneyApiTests(unittest.TestCase):
    def test_api_serializes_amounts_as_strings(self):
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(tenant_id='tenant-a')
        data = dict(property_id='prop-001', total='9007199254740993.01', currency='USD', count=1,
                    revenue_by_currency=[dict(currency='USD',total_revenue='9007199254740993.01',exact_total_revenue='9007199254740993.010',reservations_count=1)])
        with patch('app.api.v1.dashboard.get_tenant_properties', new_callable=AsyncMock, return_value=[{'timezone':'Europe/Paris'}]), patch('app.api.v1.dashboard.get_revenue_summary', new_callable=AsyncMock, return_value=data):
            with TestClient(app) as client:
                result = client.get('/dashboard/summary?property_id=prop-001').json()
        self.assertEqual(result['total_revenue'], '9007199254740993.01')
        self.assertEqual(result['revenue_by_currency'], data['revenue_by_currency'])


@unittest.skipUnless(os.getenv('RUN_DB_TESTS') == '1', 'Requires development PostgreSQL')
class MoneyPostgresTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_sql_sums_subcents_before_rounding_and_keeps_currencies_separate(self):
        pool = DatabasePool()
        await pool.initialize()
        try:
            async with pool.get_session() as session:
                await session.execute(text('CREATE TEMP TABLE reservations (property_id TEXT, tenant_id TEXT, check_in_date TIMESTAMPTZ, total_amount NUMERIC(10,3), currency TEXT)'))
                await session.execute(text("""INSERT INTO reservations VALUES
                  ('prop-001','tenant-a','2024-03-15T12:00Z',333.333,'USD'),
                  ('prop-001','tenant-a','2024-03-15T12:00Z',333.333,'USD'),
                  ('prop-001','tenant-a','2024-03-15T12:00Z',333.334,'USD'),
                  ('prop-001','tenant-a','2024-03-15T12:00Z',2.675,'EUR'),
                  ('prop-001','tenant-b','2024-03-15T12:00Z',999,'USD'),
                  ('prop-001','tenant-a','2024-04-15T12:00Z',10,'USD')"""))
                @asynccontextmanager
                async def same_session():
                    yield session
                with patch.object(reservations, 'db_pool', SimpleNamespace(initialize=AsyncMock(),get_session=same_session)):
                    result = await reservations.calculate_monthly_revenue('prop-001','tenant-a',3,2024,'Europe/Paris')
                    self.assertEqual(result['count'],4)
                    self.assertIsNone(result['total'])
                    self.assertEqual({x['currency']: x['total_revenue'] for x in result['revenue_by_currency']}, {'USD':'1000.00','EUR':'2.68'})
                    all_time = await reservations.calculate_total_revenue('prop-001','tenant-a')
                    self.assertEqual({x['currency']: x['total_revenue'] for x in all_time['revenue_by_currency']}, {'USD':'1010.00','EUR':'2.68'})
                await session.rollback()
        finally:
            await pool.close()
