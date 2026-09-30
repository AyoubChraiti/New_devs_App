import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.dashboard import get_current_user, router
from app.services import cache


def summary(tenant_id, property_id="prop-001"):
    return {
        "tenant_id": tenant_id,
        "property_id": property_id,
        "total": "2250.00" if tenant_id == "tenant-a" else "0.00",
        "currency": "USD",
        "count": 4 if tenant_id == "tenant-a" else 0,
    }


class RevenueCacheTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.entries = {}
        self.redis = AsyncMock()
        self.redis.get.side_effect = self.entries.get

        async def setex(key, ttl, value):
            self.assertEqual(ttl, 300)
            self.entries[key] = value

        self.redis.setex.side_effect = setex
        self.calculate = AsyncMock(side_effect=lambda prop, tenant: summary(tenant, prop))
        redis_patch = patch.object(cache, "redis_client", self.redis)
        calculation_patch = patch(
            "app.services.reservations.calculate_total_revenue", self.calculate
        )
        redis_patch.start()
        calculation_patch.start()
        self.addCleanup(redis_patch.stop)
        self.addCleanup(calculation_patch.stop)

    async def test_shared_property_is_isolated_in_both_request_orders(self):
        for order in [("tenant-a", "tenant-b"), ("tenant-b", "tenant-a")]:
            with self.subTest(order=order):
                self.entries.clear()
                self.calculate.reset_mock()
                for tenant in order + order:
                    result = await cache.get_revenue_summary("prop-001", tenant)
                    self.assertEqual(result, summary(tenant))
                self.assertEqual(self.calculate.await_count, 2)
                self.assertEqual(len(self.entries), 2)

    async def test_legacy_cache_is_ignored(self):
        self.entries["revenue:prop-001"] = json.dumps(summary("tenant-a"))
        result = await cache.get_revenue_summary("prop-001", "tenant-b")
        self.assertEqual(result, summary("tenant-b"))
        self.calculate.assert_awaited_once()

    async def test_invalid_cached_identity_or_json_is_replaced(self):
        await cache.get_revenue_summary("prop-001", "tenant-b")
        key = next(iter(self.entries))
        for payload in [
            json.dumps(summary("tenant-a")),
            json.dumps(summary("tenant-b", "prop-004")),
            json.dumps({"total": "9999.00"}),
            "not json",
            "null",
        ]:
            with self.subTest(payload=payload):
                self.entries[key] = payload
                self.calculate.reset_mock()
                result = await cache.get_revenue_summary("prop-001", "tenant-b")
                self.assertEqual(result, summary("tenant-b"))
                self.calculate.assert_awaited_once()
                self.assertEqual(json.loads(self.entries[key]), result)

    async def test_missing_tenant_never_accesses_cache_or_database(self):
        for tenant in [None, "", " "]:
            with self.assertRaises(ValueError):
                await cache.get_revenue_summary("prop-001", tenant)
        self.redis.get.assert_not_awaited()
        self.calculate.assert_not_awaited()

    async def test_separator_characters_do_not_collide(self):
        await cache.get_revenue_summary("b:c", "a")
        await cache.get_revenue_summary("c", "a:b")
        self.assertEqual(len(self.entries), 2)


class DashboardTenantTests(unittest.TestCase):
    def test_missing_tenant_returns_403_without_fetching_revenue(self):
        app = FastAPI()
        app.include_router(router)
        with patch("app.api.v1.dashboard.get_revenue_summary", new_callable=AsyncMock) as fetch:
            with TestClient(app) as client:
                for user in [SimpleNamespace(), SimpleNamespace(tenant_id=None),
                             SimpleNamespace(tenant_id=""), SimpleNamespace(tenant_id=" ")]:
                    app.dependency_overrides[get_current_user] = lambda: user
                    response = client.get("/dashboard/summary?property_id=prop-001")
                    self.assertEqual(response.status_code, 403)
            fetch.assert_not_awaited()
