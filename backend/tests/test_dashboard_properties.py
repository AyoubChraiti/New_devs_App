import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.api.v1.dashboard import router, get_current_user
from app.services import properties


class PropertyRoutesTests(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        app.include_router(router)
        self.user = SimpleNamespace(tenant_id='tenant-b')
        app.dependency_overrides[get_current_user] = lambda: self.user
        self.client = TestClient(app)
        self.lookup = AsyncMock()
        self.revenue = AsyncMock(return_value={
            'property_id': 'prop-001', 'total': '0', 'currency': 'USD', 'count': 0,
        })
        for target, mock in [('get_tenant_properties', self.lookup), ('get_revenue_summary', self.revenue)]:
            patcher = patch('app.api.v1.dashboard.' + target, mock)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(self.client.close)

    def test_list_uses_authenticated_tenant_ignoring_spoofed_tenant(self):
        self.lookup.return_value = [{'id': 'prop-001', 'name': 'Mountain Lodge Beta', 'timezone': 'America/New_York'}]
        response = self.client.get('/dashboard/properties?tenant_id=tenant-a', headers={'X-Simulated-Tenant': 'tenant-a'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), self.lookup.return_value)
        self.lookup.assert_awaited_once_with('tenant-b')

    def test_empty_property_list_is_valid(self):
        self.lookup.return_value = []
        self.assertEqual(self.client.get('/dashboard/properties').json(), [])

    def test_foreign_and_unknown_ids_never_reach_revenue_cache(self):
        self.lookup.return_value = []
        for prop in ['prop-002', 'nonexistent']:
            response = self.client.get('/dashboard/summary', params={'property_id': prop})
            self.assertEqual(response.status_code, 404)
            self.assertEqual(response.json(), {'detail': 'Property not found'})
        self.revenue.assert_not_awaited()

    def test_ownership_is_checked_again_on_repeated_requests(self):
        self.lookup.side_effect = [[{'id': 'prop-001'}], []]
        self.assertEqual(self.client.get('/dashboard/summary?property_id=prop-001').status_code, 200)
        self.assertEqual(self.client.get('/dashboard/summary?property_id=prop-001').status_code, 404)
        self.revenue.assert_awaited_once_with('prop-001', 'tenant-b')

    def test_property_failure_is_503_and_prevents_revenue_access(self):
        self.lookup.side_effect = properties.PropertiesUnavailableError('internal details')
        for url in ['/dashboard/properties', '/dashboard/summary?property_id=prop-001']:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 503)
            self.assertNotIn('internal details', response.text)
        self.revenue.assert_not_awaited()

    def test_missing_tenant_rejects_both_endpoints(self):
        self.user = SimpleNamespace()
        for url in ['/dashboard/properties', '/dashboard/summary?property_id=prop-001']:
            self.assertEqual(self.client.get(url).status_code, 403)
        self.lookup.assert_not_awaited()


class PropertyQueryTests(unittest.IsolatedAsyncioTestCase):
    async def test_query_scopes_both_list_and_lookup(self):
        pool = MagicMock()
        pool.initialize = AsyncMock()
        session = AsyncMock()
        pool.get_session.return_value.__aenter__.return_value = session
        result = MagicMock()
        result.mappings.return_value.all.return_value = [{'id': 'prop-001', 'name': 'Mountain Lodge Beta', 'timezone': 'America/New_York'}]
        session.execute.return_value = result
        with patch.object(properties, 'db_pool', pool):
            await properties.get_tenant_properties('tenant-b')
            sql, params = session.execute.call_args.args
            self.assertIn('WHERE tenant_id = :tenant_id', str(sql))
            self.assertEqual(params, {'tenant_id': 'tenant-b'})
            rows = await properties.get_tenant_properties('tenant-b', 'prop-001')
            sql, params = session.execute.call_args.args
            self.assertIn('AND id = :property_id', str(sql))
            self.assertEqual(params, {'tenant_id': 'tenant-b', 'property_id': 'prop-001'})
            self.assertEqual(rows[0]['name'], 'Mountain Lodge Beta')

    async def test_database_error_is_not_an_empty_property_list(self):
        pool = MagicMock()
        pool.initialize = AsyncMock(side_effect=OperationalError('SELECT', {}, Exception('unavailable')))
        with patch.object(properties, 'db_pool', pool), self.assertLogs('app.services.properties', level='ERROR'):
            with self.assertRaises(properties.PropertiesUnavailableError):
                await properties.get_tenant_properties('tenant-b')
