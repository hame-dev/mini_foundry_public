"use client";

import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";

type UsageBreakdown = {
  resource_type: string;
  total_credits: number;
  count: number;
};

type UsageLog = {
  id: string;
  resource_type: string;
  resource_id: string | null;
  compute_credits: number;
  execution_time_ms: number;
  created_at: string;
};

type GovernanceResponse = {
  total_credits: number;
  breakdown: UsageBreakdown[];
  recent_logs: UsageLog[];
};

export default function GovernancePage() {
  const [data, setData] = useState<GovernanceResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiFetch<GovernanceResponse>("/governance/metrics")
      .then(setData)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="p-6 text-gray-500 font-medium">Loading Resource Governance Dashboard...</div>;
  if (error) return <div className="p-6 text-red-650 font-medium">Error loading data: {error}</div>;

  const total = data?.total_credits ?? 0;
  const logsCount = data?.recent_logs.length ?? 0;

  return (
    <div className="space-y-6">
      <header className="page-header">
        <div>
          <div className="page-header-eyebrow">Enterprise Governance</div>
          <h1 className="page-header-title">Resource Governance & Compute Costs</h1>
          <p className="text-xs text-gray-500 mt-1">
            Monitor compute credit expenditures across SQL queries, pipeline compilations, and AIP Logic canvas executions.
          </p>
        </div>
      </header>

      {/* Main KPI cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <div className="app-card p-5 flex flex-col justify-between">
          <span className="text-xs font-bold text-gray-400 uppercase tracking-wider">Total Compute Credits Expended</span>
          <div className="mt-3 flex items-baseline gap-2">
            <span className="text-3xl font-black font-sans" style={{ color: "var(--text)" }}>{total.toFixed(4)}</span>
            <span className="text-sm font-semibold text-gray-400">credits</span>
          </div>
          <p className="text-[10px] text-gray-400 mt-2">Calculated in real-time based on execution time and base weights</p>
        </div>

        <div className="app-card p-5 flex flex-col justify-between">
          <span className="text-xs font-bold text-gray-400 uppercase tracking-wider">Total Tracked Computes</span>
          <div className="mt-3 flex items-baseline gap-2">
            <span className="text-3xl font-black font-sans" style={{ color: "var(--text)" }}>
              {data?.breakdown.reduce((sum, item) => sum + item.count, 0) ?? 0}
            </span>
            <span className="text-sm font-semibold text-gray-400">operations</span>
          </div>
          <p className="text-[10px] text-gray-400 mt-2">Active logging of workspace transactions</p>
        </div>

        <div className="app-card p-5 flex flex-col justify-between">
          <span className="text-xs font-bold text-gray-400 uppercase tracking-wider">Average Compute Cost</span>
          <div className="mt-3 flex items-baseline gap-2">
            <span className="text-3xl font-black font-sans" style={{ color: "var(--text)" }}>
              {total > 0
                ? (total / (data?.breakdown.reduce((sum, item) => sum + item.count, 0) || 1)).toFixed(4)
                : "0.0000"}
            </span>
            <span className="text-sm font-semibold text-gray-400">credits / op</span>
          </div>
          <p className="text-[10px] text-gray-400 mt-2">Resource efficiency coefficient</p>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Breakdown Panel */}
        <div className="lg:col-span-1 app-card p-5 space-y-4">
          <h3 className="text-sm font-bold text-gray-800 border-b pb-2">Credit Expenditure by Resource Type</h3>
          <div className="space-y-4">
            {data?.breakdown.map((item) => {
              const percentage = total > 0 ? (item.total_credits / total) * 100 : 0;
              return (
                <div key={item.resource_type} className="space-y-1">
                  <div className="flex justify-between text-xs font-semibold text-gray-700">
                    <span className="uppercase">{item.resource_type}</span>
                    <span>
                      {item.total_credits.toFixed(3)} ({percentage.toFixed(0)}%)
                    </span>
                  </div>
                  <div className="w-full bg-gray-100 rounded-full h-2 overflow-hidden">
                    <div
                      className="bg-blue-650 h-full rounded-full transition-all duration-500"
                      style={{ width: `${percentage}%` }}
                    />
                  </div>
                  <div className="text-[10px] text-gray-400 font-medium font-sans">
                    {item.count} executions
                  </div>
                </div>
              );
            })}
            {(!data?.breakdown || data.breakdown.length === 0) && (
              <div className="text-center text-xs text-gray-400 py-6">No executions recorded.</div>
            )}
          </div>
        </div>

        {/* Audit Log Panel */}
        <div className="lg:col-span-2 app-card p-5 flex flex-col">
          <h3 className="text-sm font-bold text-gray-800 border-b pb-2">Recent Compute Expenditures</h3>
          <div className="flex-1 overflow-x-auto mt-3">
            <table className="w-full text-xs text-left">
              <thead className="bg-gray-50 border-b text-gray-500 font-bold">
                <tr>
                  <th className="px-3 py-2">Resource Type</th>
                  <th className="px-3 py-2">Execution Time</th>
                  <th className="px-3 py-2">Credits Consumed</th>
                  <th className="px-3 py-2 text-right">Timestamp</th>
                </tr>
              </thead>
              <tbody>
                {data?.recent_logs.map((log) => (
                  <tr key={log.id} className="border-b hover:bg-gray-50 transition-colors">
                    <td className="px-3 py-2.5">
                      <span className="px-2 py-0.5 rounded bg-blue-50 text-blue-700 font-mono text-[10px] uppercase font-bold">
                        {log.resource_type}
                      </span>
                    </td>
                    <td className="px-3 py-2.5 font-mono text-gray-600">
                      {log.execution_time_ms.toLocaleString()} ms
                    </td>
                    <td className="px-3 py-2.5 font-mono font-bold text-gray-800">
                      {log.compute_credits.toFixed(5)}
                    </td>
                    <td className="px-3 py-2.5 font-mono text-gray-450 text-right">
                      {new Date(log.created_at).toLocaleTimeString()}
                    </td>
                  </tr>
                ))}
                {logsCount === 0 && (
                  <tr>
                    <td colSpan={4} className="text-center text-xs text-gray-400 py-6">
                      No logs recorded.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
}
