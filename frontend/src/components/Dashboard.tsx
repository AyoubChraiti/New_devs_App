import React, { useEffect, useState } from "react";
import { RevenueSummary } from "./RevenueSummary";

import { SecureAPI } from "../lib/secureApi";
import { useAuth } from "../contexts/AuthContext.new";

interface DashboardProperty {
  id: string;
  name: string;
  timezone: string;
}

const Dashboard: React.FC = () => {
  const { user } = useAuth();
  // Remount account-specific state immediately when the authenticated account changes.
  return <TenantDashboard key={JSON.stringify([user?.id, user?.tenant_id])} />;
};

const TenantDashboard: React.FC = () => {
  const [properties, setProperties] = useState<DashboardProperty[]>([]);
  const [selectedProperty, setSelectedProperty] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [period, setPeriod] = useState('all');
  const [reportMonth, setReportMonth] = useState(() => {
    const today = new Date();
    return `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}`;
  });
  const validMonth = /^\d{4}-(0[1-9]|1[0-2])$/.test(reportMonth)
    && Number(reportMonth.slice(0, 4)) >= 1 && Number(reportMonth.slice(0, 4)) <= 9998;

  useEffect(() => {
    let active = true;
    SecureAPI.getDashboardProperties().then((items) => {
      if (!active) return;
      setProperties(items);
      setSelectedProperty(items[0]?.id ?? '');
    }).catch(() => {
      if (active) setError('Failed to load properties. Please refresh to try again.');
    }).finally(() => {
      if (active) setLoading(false);
    });
    return () => { active = false; };
  }, []);

  return (
    <div className="p-4 lg:p-6 min-h-full">
      <div className="max-w-7xl mx-auto">
        <h1 className="text-2xl font-bold mb-6 text-gray-900">Property Management Dashboard</h1>

        <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-4 lg:p-6">
          <div className="mb-6">
            <div className="flex flex-col sm:flex-row sm:justify-between sm:items-start gap-4">
              <div>
                <h2 className="text-lg lg:text-xl font-medium text-gray-900 mb-2">Revenue Overview</h2>
                <p className="text-sm lg:text-base text-gray-600">
                  Revenue insights for your properties
                </p>
              </div>
              
              {/* Property Selector */}
              <div className="flex flex-col sm:items-end">
                <label htmlFor="dashboard-property" className="text-xs font-medium text-gray-700 mb-1">Select Property</label>
                <select
                  id="dashboard-property"
                  disabled={loading || !!error || properties.length === 0}
                  value={selectedProperty}
                  onChange={(e) => setSelectedProperty(e.target.value)}
                  className="block w-full sm:w-auto min-w-[200px] px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-blue-500 focus:border-blue-500 text-sm"
                >
                  {!selectedProperty && <option value="">Select Property</option>}
                  {properties.map((property) => (
                    <option key={property.id} value={property.id}>
                      {property.name}
                    </option>
                  ))}
                </select>
              </div>
            </div>
          </div>

          <div className="flex flex-wrap items-end gap-4 mb-6">
            <label className="text-sm text-gray-700">
              Reporting period
              <select value={period} onChange={(event) => setPeriod(event.target.value)} className="block border rounded-md p-2 mt-1">
                <option value="all">All time</option>
                <option value="monthly">Monthly</option>
              </select>
            </label>
            {period === 'monthly' && (
              <label className="text-sm text-gray-700">
                Month
                <input type="month" min="0001-01" max="9998-12" value={reportMonth}
                  onChange={(event) => setReportMonth(event.target.value)} className="block border rounded-md p-2 mt-1" />
              </label>
            )}
          </div>
          {period === 'monthly' && <p className="text-sm text-gray-600 mb-4">
            Based on check-in dates in {properties.find((property) => property.id === selectedProperty)?.timezone || 'the property’s local time zone'}.
          </p>}
          {period === 'monthly' && !validMonth && <p role="alert">Select a valid reporting month.</p>}
          <div className="space-y-6">
            {loading && <p role="status">Loading properties…</p>}
            {error && <p role="alert" className="text-red-600">{error}</p>}
            {!loading && !error && properties.length === 0 && <p>No properties available for your account.</p>}
            {!loading && !error && selectedProperty && (period === 'all' || validMonth) && (
              <RevenueSummary key={`${selectedProperty}:${period}:${reportMonth}`} propertyId={selectedProperty}
                month={period === 'monthly' ? Number(reportMonth.slice(5, 7)) : undefined}
                year={period === 'monthly' ? Number(reportMonth.slice(0, 4)) : undefined} />
            )}
          </div>
        </div>
      </div>
    </div>
  );
};

export default Dashboard;
