"use client";
import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";

type Schedule = {
  id: string;
  name: string;
  job_type: string;
  cron_expression: string;
  input: Record<string, unknown> | null;
  enabled: boolean;
  last_run_at: string | null;
  next_run_at: string | null;
};

export default function SchedulesPage() {
  const [items, setItems] = useState<Schedule[]>([]);
  const [jobTypes, setJobTypes] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);

  const [name, setName] = useState("");
  const [jobType, setJobType] = useState("");
  const [cron, setCron] = useState("0 * * * *");
  const [inputJson, setInputJson] = useState("{}");

  async function load() {
    try {
      const [list, meta] = await Promise.all([
        apiFetch<Schedule[]>("/admin/schedules"),
        apiFetch<{ job_types: string[] }>("/jobs/_meta/job-types"),
      ]);
      setItems(list);
      setJobTypes(meta.job_types);
      if (!jobType && meta.job_types.length) setJobType(meta.job_types[0]);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }
  useEffect(() => { load(); }, []);  // eslint-disable-line react-hooks/exhaustive-deps

  async function create(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      let input: unknown = {};
      try { input = JSON.parse(inputJson); } catch { throw new Error("input is not valid JSON"); }
      await apiFetch("/admin/schedules", {
        method: "POST",
        body: JSON.stringify({ name, job_type: jobType, cron_expression: cron, input, enabled: true }),
      });
      setName(""); setCron("0 * * * *"); setInputJson("{}");
      load();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  async function runNow(id: string) {
    try { await apiFetch(`/admin/schedules/${id}/run-now`, { method: "POST" }); load(); }
    catch (e: unknown) { setError(e instanceof Error ? e.message : String(e)); }
  }

  async function remove(id: string) {
    if (!confirm("Delete schedule?")) return;
    try { await apiFetch(`/admin/schedules/${id}`, { method: "DELETE" }); load(); }
    catch (e: unknown) { setError(e instanceof Error ? e.message : String(e)); }
  }

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold">Schedules</h1>
      {error && <div className="text-red-600 text-sm">{error}</div>}

      <form onSubmit={create} className="app-card p-4 grid grid-cols-5 gap-2 items-end">
        <div>
          <label className="block text-xs mb-1">Name</label>
          <input className="input-dark w-full" required
            value={name} onChange={(e) => setName(e.target.value)} />
        </div>
        <div>
          <label className="block text-xs mb-1">Job type</label>
          <select className="input-dark w-full"
            value={jobType} onChange={(e) => setJobType(e.target.value)}>
            {jobTypes.map((t) => <option key={t}>{t}</option>)}
          </select>
        </div>
        <div>
          <label className="block text-xs mb-1">Cron</label>
          <input className="input-dark w-full font-mono" required
            value={cron} onChange={(e) => setCron(e.target.value)} />
        </div>
        <div>
          <label className="block text-xs mb-1">Input (JSON)</label>
          <input className="input-dark w-full font-mono"
            value={inputJson} onChange={(e) => setInputJson(e.target.value)} />
        </div>
        <button className="btn-primary text-sm py-1">Create</button>
      </form>

      <div className="app-card overflow-hidden">
      <table className="data-table">
        <thead>
          <tr>
            <th className="px-4 py-2">Name</th>
            <th className="px-4 py-2">Type</th>
            <th className="px-4 py-2">Cron</th>
            <th className="px-4 py-2">Last</th>
            <th className="px-4 py-2">Next</th>
            <th className="px-4 py-2"></th>
          </tr>
        </thead>
        <tbody>
          {items.map((s) => (
            <tr key={s.id} className="border-t">
              <td className="px-4 py-2">{s.name}</td>
              <td className="px-4 py-2 font-mono text-xs">{s.job_type}</td>
              <td className="px-4 py-2 font-mono text-xs">{s.cron_expression}</td>
              <td className="px-4 py-2 text-xs text-gray-500">{s.last_run_at ? new Date(s.last_run_at).toLocaleString() : "—"}</td>
              <td className="px-4 py-2 text-xs text-gray-500">{s.next_run_at ? new Date(s.next_run_at).toLocaleString() : "—"}</td>
              <td className="px-4 py-2 space-x-2 text-right">
                <button onClick={() => runNow(s.id)} className="text-xs border rounded px-2 py-1">Run now</button>
                <button onClick={() => remove(s.id)} className="text-xs text-red-600 border border-red-200 rounded px-2 py-1">Delete</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      </div>
    </div>
  );
}
