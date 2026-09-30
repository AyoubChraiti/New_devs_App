import { afterEach, expect, it, vi } from 'vitest';

vi.mock('./supabase', () => ({ supabase: { from: vi.fn() } }));
vi.mock('../utils/sessionManager', () => ({ sessionManager: {} }));
vi.mock('../utils/apiErrorHandler', () => ({ withRetry: vi.fn(), handleApiError: vi.fn(), classifyError: vi.fn() }));
import { SecureAPI } from './secureApi';

afterEach(() => vi.restoreAllMocks());

it('encodes monthly selections in the actual API URL', async () => {
  const request = vi.spyOn(SecureAPI as any, 'request').mockResolvedValue({});
  await SecureAPI.getDashboardSummary('prop & 001', { month: 3, year: 2024 });
  const url = new URL(request.mock.calls[0][0] as string, 'http://localhost');
  expect(url.pathname).toBe('/api/v1/dashboard/summary');
  expect(url.searchParams.get('property_id')).toBe('prop & 001');
  expect(url.searchParams.get('month')).toBe('3');
  expect(url.searchParams.get('year')).toBe('2024');
});

it('omits period parameters when requesting all-time revenue', async () => {
  const request = vi.spyOn(SecureAPI as any, 'request').mockResolvedValue({});
  await SecureAPI.getDashboardSummary('prop-001');
  const url = new URL(request.mock.calls[0][0] as string, 'http://localhost');
  expect(url.searchParams.has('month')).toBe(false);
  expect(url.searchParams.has('year')).toBe(false);
});
