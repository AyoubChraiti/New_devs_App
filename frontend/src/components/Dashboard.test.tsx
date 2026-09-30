import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import Dashboard from './Dashboard';

const mocks = vi.hoisted(() => ({
  properties: vi.fn(), summary: vi.fn(), user: { id: 'sunset', tenant_id: 'tenant-a' },
}));
vi.mock('../lib/secureApi', () => ({ SecureAPI: {
  getDashboardProperties: mocks.properties, getDashboardSummary: mocks.summary,
} }));
vi.mock('../contexts/AuthContext.new', () => ({ useAuth: () => ({ user: mocks.user }) }));

const sunset = [
  { id: 'prop-001', name: 'Beach House Alpha', timezone: 'Europe/Paris' },
  { id: 'prop-002', name: 'City Apartment Downtown', timezone: 'Europe/Paris' },
];
const response = (total: number, id = 'prop-001') => ({
  property_id: id, total_revenue: total, currency: 'USD', reservations_count: total ? 4 : 0,
});
const deferred = () => {
  let resolve!: (value: ReturnType<typeof response>) => void;
  const promise = new Promise<ReturnType<typeof response>>(r => { resolve = r; });
  return { promise, resolve };
};
async function ready() {
  render(<Dashboard />);
  await screen.findByText('USD 2,250.00');
}
function monthly(month: string) {
  fireEvent.change(screen.getByLabelText('Reporting period'), { target: { value: 'monthly' } });
  fireEvent.change(screen.getByLabelText('Month'), { target: { value: month } });
}

beforeEach(() => {
  mocks.user = { id: 'sunset', tenant_id: 'tenant-a' };
  mocks.properties.mockReset().mockResolvedValue(sunset);
  mocks.summary.mockReset().mockResolvedValue(response(2250));
});
afterEach(cleanup);

describe('dashboard reporting controls', () => {
  it('loads owned properties and defaults to an explicitly all-time total', async () => {
    await ready();
    expect(screen.getByText('All-time Revenue')).toBeTruthy();
    expect(screen.queryByLabelText('Month')).toBeNull();
    expect(mocks.summary).toHaveBeenLastCalledWith('prop-001', expect.objectContaining({ month: undefined, year: undefined }));
    expect(screen.queryByText('12%')).toBeNull();
  });

  it('passes selected month/year, property and resets parameters for all time', async () => {
    await ready();
    monthly('2024-03');
    await screen.findByText('Monthly Revenue');
    expect(mocks.summary).toHaveBeenLastCalledWith('prop-001', expect.objectContaining({ month: 3, year: 2024 }));
    expect(screen.getByText(/Based on check-in dates in Europe\/Paris/)).toBeTruthy();
    fireEvent.change(screen.getByLabelText('Select Property'), { target: { value: 'prop-002' } });
    await waitFor(() => expect(mocks.summary).toHaveBeenLastCalledWith('prop-002', expect.objectContaining({ month: 3, year: 2024 })));
    fireEvent.change(screen.getByLabelText('Reporting period'), { target: { value: 'all' } });
    await screen.findByText('All-time Revenue');
    expect(mocks.summary).toHaveBeenLastCalledWith('prop-002', expect.objectContaining({ month: undefined, year: undefined }));
  });

  it('does not request revenue when the month is cleared or out of range', async () => {
    await ready();
    monthly('2024-03');
    await screen.findByText('Monthly Revenue');
    const count = mocks.summary.mock.calls.length;
    for (const month of ['', '9999-03']) {
      fireEvent.change(screen.getByLabelText('Month'), { target: { value: month } });
      expect(screen.getByRole('alert').textContent).toContain('Select a valid reporting month');
      expect(screen.queryByText('USD 2,250.00')).toBeNull();
    }
    expect(mocks.summary).toHaveBeenCalledTimes(count);
  });

  it('ignores late responses when users rapidly switch months', async () => {
    await ready();
    const march = deferred();
    mocks.summary.mockImplementation((_id, options) => options.month === 3 ? march.promise : Promise.resolve(response(0)));
    monthly('2024-03');
    fireEvent.change(screen.getByLabelText('Month'), { target: { value: '2024-04' } });
    await screen.findByText('USD 0.00');
    await act(async () => { march.resolve(response(2250)); });
    expect(screen.getByText('USD 0.00')).toBeTruthy();
    expect(screen.queryByText('USD 2,250.00')).toBeNull();
  });

  it('shows a revenue error and recovers after changing month', async () => {
    await ready();
    const errorLog = vi.spyOn(console, 'error').mockImplementation(() => {});
    try {
      mocks.summary.mockRejectedValue(new Error('503'));
      monthly('2024-03');
      expect((await screen.findByRole('alert')).textContent).toContain('Failed to load revenue data');
      expect(screen.queryByText('USD 2,250.00')).toBeNull();
      mocks.summary.mockResolvedValue(response(0));
      fireEvent.change(screen.getByLabelText('Month'), { target: { value: '2024-04' } });
      await screen.findByText('USD 0.00');
      expect(screen.queryByRole('alert')).toBeNull();
    } finally { errorLog.mockRestore(); }
  });

  it('clears the old account properties and revenue during an account switch', async () => {
    const view = render(<Dashboard />);
    await screen.findByText('USD 2,250.00');
    mocks.user = { id: 'ocean', tenant_id: 'tenant-b' };
    mocks.properties.mockResolvedValue([{ id: 'prop-001', name: 'Mountain Lodge Beta', timezone: 'America/New_York' }]);
    mocks.summary.mockResolvedValue(response(0));
    view.rerender(<Dashboard />);
    expect(screen.queryByText('Beach House Alpha')).toBeNull();
    expect(screen.queryByText('USD 2,250.00')).toBeNull();
    await screen.findByText('Mountain Lodge Beta');
    await screen.findByText('USD 0.00');
    monthly('2024-03');
    expect(screen.getByText(/Based on check-in dates in America\/New_York/)).toBeTruthy();
  });

  it('does not fetch revenue for an empty property list', async () => {
    mocks.properties.mockResolvedValue([]);
    render(<Dashboard />);
    await screen.findByText('No properties available for your account.');
    expect(mocks.summary).not.toHaveBeenCalled();
  });

  it('shows property loading and failure without requesting revenue', async () => {
    let reject!: (reason: Error) => void;
    mocks.properties.mockReturnValue(new Promise((_resolve, rejectPromise) => { reject = rejectPromise; }));
    render(<Dashboard />);
    expect(screen.getByRole('status').textContent).toBe('Loading properties…');
    await act(async () => { reject(new Error('503')); });
    expect(screen.getByRole('alert').textContent).toContain('Failed to load properties');
    expect(mocks.summary).not.toHaveBeenCalled();
  });
});
