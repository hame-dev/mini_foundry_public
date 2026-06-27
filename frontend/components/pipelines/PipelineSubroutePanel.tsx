"use client";

import Link from "next/link";
import { use, useCallback, useEffect, useMemo, useState } from "react";
import { ResourceHeader } from "@/components/platform/ResourceHeader";
import { EmptyState, ErrorState, LoadingState } from "@/components/platform/States";
import { StatusPill } from "@/components/foundry";
import { apiFetch } from "@/lib/api";
import { operationsApi, type Job } from "@/lib/api/endpoints/operations";
import type { PipelineDetail } from "@/lib/pipelines";

type Mode = "builds" | "schedules" | "expectations" | "lineage" | "branches";
type Branch = { id: string; name: string; status: string; created_at: string; merged_at: string | null };
type Resource = { id: string; object_id: string | null; name: string; resource_type: string };
type ResourceVersion = { id: string; branch_name: string; state: string; created_at: string };
type Schedule = { id: string; name: string; job_type: string; cron_expression: string; enabled: boolean; next_run_at: string | null; resource_id?: string | null; input?: Record<string, unknown> | null };
type Validation = { status: string; warnings: unknown[]; errors: unknown[] };

const TITLE: Record<Mode, string> = {
  builds: "Pipeline builds",
  schedules: "Pipeline schedules",
  expectations: "Pipeline expectations",
  lineage: "Pipeline lineage",
  branches: "Pipeline branches",
};

export function PipelineSubroutePanel({ params, mode }: { params: Promise<{ id: string }>; mode: Mode }) {
  const { id } = use(params);
  const [pipeline, setPipeline] = useState<PipelineDetail | null>(null);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [branches, setBranches] = useState<Branch[]>([]);
  const [resource, setResource] = useState<Resource | null>(null);
  const [schedules, setSchedules] = useState<Schedule[]>([]);
  const [validation, setValidation] = useState<Validation | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const p = await apiFetch<PipelineDetail>(`/pipelines/${id}`);
      setPipeline(p);
      if (mode === "builds") {
        const rows = await operationsApi.jobs();
        setJobs(rows.filter((job) => job.resource_type === "pipeline" && job.resource_id === id));
      }
      if (mode === "branches") {
        const rows = await apiFetch<Resource[]>("/platform/resources?resource_type=pipeline&limit=500");
        const pipelineResource = rows.find((row) => row.object_id === id) ?? null;
        setResource(pipelineResource);
        if (pipelineResource) {
          const versions = await apiFetch<ResourceVersion[]>(`/platform/resources/${pipelineResource.id}/versions`).catch(() => []);
          const latestByBranch = new Map<string, ResourceVersion>();
          for (const version of versions) {
            if (version.branch_name === "main") continue;
            if (!latestByBranch.has(version.branch_name)) latestByBranch.set(version.branch_name, version);
          }
          setBranches(Array.from(latestByBranch.values()).map((version) => ({
            id: version.id,
            name: version.branch_name,
            status: version.state || "draft",
            created_at: version.created_at,
            merged_at: null,
          })));
        } else {
          setBranches([]);
        }
      }
      if (mode === "lineage") {
        const rows = await apiFetch<Resource[]>("/platform/resources?resource_type=pipeline&limit=500");
        setResource(rows.find((row) => row.object_id === id) ?? null);
      }
      if (mode === "schedules") {
        const rows = await apiFetch<Schedule[]>("/admin/schedules").catch(() => []);
        setSchedules(rows.filter((row) => {
          if (row.resource_id === id) return true;
          const input = row.input ?? {};
          return input.pipeline_id === id || (row.job_type.includes("pipeline") && input.resource_id === id);
        }));
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load pipeline route.");
    } finally {
      setLoading(false);
    }
  }, [id, mode]);

  useEffect(() => {
    void load();
  }, [load]);

  const branchRows = useMemo(() => branches.filter((branch) => branch.status !== "abandoned"), [branches]);

  async function validate() {
    setBusy(true);
    setError(null);
    try {
      setValidation(await apiFetch<Validation>(`/pipelines/${id}/validate`, { method: "POST" }));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Validation failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-5">
      <ResourceHeader
        title={pipeline?.name ?? TITLE[mode]}
        type="Build / Pipeline"
        status={pipeline?.last_run_status ?? "draft"}
        subtitle={TITLE[mode]}
        actions={
          <div className="flex gap-2">
            <Link className="toolbar-button" href={`/build/pipelines/${id}/graph`}>Graph</Link>
            <Link className="toolbar-button" href={`/build/pipelines/${id}/preview`}>Preview</Link>
          </div>
        }
      />

      {loading ? <LoadingState label="Loading pipeline..." /> : null}
      {error ? <ErrorState message={error} /> : null}

      {!loading && mode === "builds" ? (
        <section className="app-card overflow-hidden">
          {jobs.length ? (
            <table className="data-table text-sm">
              <thead><tr><th>Job</th><th>Status</th><th>Created</th><th>Finished</th></tr></thead>
              <tbody>{jobs.map((job) => (
                <tr key={job.id}>
                  <td><Link className="font-mono hover:underline" href={`/operations/jobs/${job.id}`}>{job.id.slice(0, 8)}</Link></td>
                  <td><StatusPill status={job.status} /></td>
                  <td>{new Date(job.created_at).toLocaleString()}</td>
                  <td>{job.finished_at ? new Date(job.finished_at).toLocaleString() : "-"}</td>
                </tr>
              ))}</tbody>
            </table>
          ) : <div className="p-4"><EmptyState title="No build jobs" detail="Pipeline run jobs will appear here." /></div>}
        </section>
      ) : null}

      {!loading && mode === "schedules" ? (
        <section className="app-card overflow-hidden">
          {schedules.length ? (
            <table className="data-table text-sm">
              <thead><tr><th>Name</th><th>Cron</th><th>Status</th><th>Next run</th></tr></thead>
              <tbody>{schedules.map((schedule) => (
                <tr key={schedule.id}>
                  <td>{schedule.name}</td>
                  <td className="font-mono">{schedule.cron_expression}</td>
                  <td>{schedule.enabled ? "enabled" : "disabled"}</td>
                  <td>{schedule.next_run_at ? new Date(schedule.next_run_at).toLocaleString() : "-"}</td>
                </tr>
              ))}</tbody>
            </table>
          ) : <div className="p-4"><EmptyState title="No schedules" detail="Schedules targeting this pipeline will appear here." /></div>}
        </section>
      ) : null}

      {!loading && mode === "expectations" ? (
        <section className="app-card p-4">
          <div className="flex items-center justify-between gap-3">
            <div>
              <h2 className="font-semibold">Validation expectations</h2>
              <p className="text-sm text-[var(--muted)]">Run graph validation before preview, publish, or branch review.</p>
            </div>
            <button className="toolbar-button" type="button" onClick={() => void validate()} disabled={busy}>{busy ? "Running" : "Validate"}</button>
          </div>
          {validation ? (
            <div className="mt-4 space-y-3">
              {validation.errors.length ? (
                <table className="data-table text-sm">
                  <thead><tr><th>Code</th><th>Message</th><th>Status</th></tr></thead>
                  <tbody>
                    {validation.errors.map((item, index) => {
                      const row = item as { code?: string; message?: string };
                      return (
                        <tr key={`err-${index}`}>
                          <td className="font-mono">{row.code ?? "error"}</td>
                          <td>{row.message ?? String(item)}</td>
                          <td><StatusPill status="failed" /></td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              ) : null}
              {validation.warnings.length ? (
                <table className="data-table text-sm">
                  <thead><tr><th>Code</th><th>Message</th><th>Status</th></tr></thead>
                  <tbody>
                    {validation.warnings.map((item, index) => {
                      const row = item as { code?: string; message?: string };
                      return (
                        <tr key={`warn-${index}`}>
                          <td className="font-mono">{row.code ?? "warning"}</td>
                          <td>{row.message ?? String(item)}</td>
                          <td><StatusPill status="needs approval" /></td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              ) : !validation.errors.length ? (
                <EmptyState title="No issues" detail="Validation completed without warnings." />
              ) : null}
            </div>
          ) : null}
        </section>
      ) : null}

      {!loading && mode === "lineage" ? (
        <section className="app-card p-4">
          {resource ? (
            <>
              <h2 className="font-semibold">Resource lineage</h2>
              <p className="mt-1 text-sm text-[var(--muted)]">Open the permission-safe lineage and impact graph for this pipeline resource.</p>
              <Link className="toolbar-button mt-4 inline-flex" href={`/data/lineage/${resource.id}`}>Open lineage graph</Link>
            </>
          ) : <EmptyState title="No platform resource" detail="Save or run the pipeline once to register a lineage resource." />}
        </section>
      ) : null}

      {!loading && mode === "branches" ? (
        <section className="app-card overflow-hidden">
          {branchRows.length ? (
            <table className="data-table text-sm">
              <thead><tr><th>Branch</th><th>Status</th><th>Created</th><th>Merged</th></tr></thead>
              <tbody>{branchRows.map((branch) => (
                <tr key={branch.id}>
                  <td>{branch.name}</td>
                  <td><StatusPill status={branch.status} /></td>
                  <td>{new Date(branch.created_at).toLocaleString()}</td>
                  <td>{branch.merged_at ? new Date(branch.merged_at).toLocaleString() : "-"}</td>
                </tr>
              ))}</tbody>
            </table>
          ) : <div className="p-4"><EmptyState title="No branches" detail="Active and review branches will appear here." /></div>}
        </section>
      ) : null}
    </div>
  );
}
