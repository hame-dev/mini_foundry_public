"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { apiFetch } from "@/lib/api";

type Tab = "csv" | "postgres" | "rest" | "parquet";

const AI_POLICIES = ["local_only", "cloud_allowed", "metadata_only", "no_external"];

type CsvPreview = {
  encoding: string;
  columns: { source_name: string; name: string; type: string; sample: unknown[] }[];
  sample_rows: Record<string, unknown>[];
  column_count: number;
  wide_file: boolean;
};

export default function NewConnectorPage() {
  const router = useRouter();
  const [tab, setTab] = useState<Tab>("csv");
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  function ok(text: string) { setMsg(text); setErr(null); }
  function fail(text: string) { setErr(text); setMsg(null); }

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">New connector</h1>
      <div className="flex gap-2 border-b">
        {(["csv", "postgres", "rest", "parquet"] as Tab[]).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-4 py-2 text-sm ${tab === t ? "border-b-2 border-black font-medium" : "text-gray-500"}`}
          >
            {t.toUpperCase()}
          </button>
        ))}
      </div>

      {msg && <div className="text-sm text-green-700 bg-green-50 border border-green-200 rounded p-2">{msg}</div>}
      {err && <div className="text-sm text-red-700 bg-red-50 border border-red-200 rounded p-2">{err}</div>}

      {tab === "csv" && (
        <CsvForm busy={busy} setBusy={setBusy} ok={ok} fail={fail} done={() => router.push("/catalog")} />
      )}
      {tab === "postgres" && (
        <PostgresForm busy={busy} setBusy={setBusy} ok={ok} fail={fail} done={() => router.push("/catalog")} />
      )}
      {tab === "rest" && (
        <RestForm busy={busy} setBusy={setBusy} ok={ok} fail={fail} done={() => router.push("/catalog")} />
      )}
      {tab === "parquet" && (
        <ParquetForm busy={busy} setBusy={setBusy} ok={ok} fail={fail} done={() => router.push("/catalog")} />
      )}
    </div>
  );
}

function ParquetForm({ busy, setBusy, ok, fail, done }: FormProps) {
  const [name, setName] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [policy, setPolicy] = useState("local_only");

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!file) return fail("Pick a .parquet file");
    setBusy(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      fd.append("dataset_name", name);
      fd.append("ai_policy", policy);
      const data = await apiFetch<{ dataset_id: string; columns: number; storage_uri: string }>("/connectors/parquet", {
        method: "POST",
        body: fd,
      });
      ok(`Registered dataset ${data.dataset_id} (${data.columns} columns) at ${data.storage_uri}`);
      setTimeout(done, 800);
    } catch (e: unknown) {
      fail(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-3 app-card p-4">
      <div>
        <label className="block text-sm font-medium mb-1">Dataset name</label>
        <input type="text" required value={name}
          onChange={(e) => setName(e.target.value)}
          className="input-dark w-full" />
      </div>
      <div>
        <label className="block text-sm font-medium mb-1">Parquet file</label>
        <input type="file" accept=".parquet" onChange={(e) => setFile(e.target.files?.[0] || null)} />
      </div>
      <div>
        <label className="block text-sm font-medium mb-1">AI policy</label>
        <select value={policy} onChange={(e) => setPolicy(e.target.value)}
          className="input-dark w-full">
          {AI_POLICIES.map((o) => <option key={o} value={o}>{o}</option>)}
        </select>
      </div>
      <button disabled={busy} className="btn-primary px-4 py-2 disabled:opacity-50">
        {busy ? "Uploading..." : "Upload to object storage"}
      </button>
    </form>
  );
}

type FormProps = {
  busy: boolean;
  setBusy: (b: boolean) => void;
  ok: (m: string) => void;
  fail: (m: string) => void;
  done: () => void;
};

function CsvForm({ busy, setBusy, ok, fail, done }: FormProps) {
  const [name, setName] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [policy, setPolicy] = useState("local_only");
  const [encoding, setEncoding] = useState("");
  const [preview, setPreview] = useState<CsvPreview | null>(null);

  async function previewSchema() {
    if (!file) return fail("Pick a CSV file");
    setBusy(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      if (encoding.trim()) fd.append("encoding", encoding.trim());
      const data = await apiFetch<CsvPreview>("/connectors/csv/preview", { method: "POST", body: fd });
      setPreview(data);
      setEncoding(data.encoding);
      ok(`Detected ${data.column_count} columns using ${data.encoding}`);
    } catch (e: unknown) {
      fail(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!file) return fail("Pick a CSV file");
    if (!preview) return fail("Preview and confirm the inferred schema before upload");
    setBusy(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      fd.append("dataset_name", name);
      fd.append("ai_policy", policy);
      fd.append("encoding", encoding);
      const data = await apiFetch<{ dataset_id: string; row_count: number }>("/connectors/csv", {
        method: "POST",
        body: fd,
      });
      ok(`Created dataset ${data.dataset_id} (${data.row_count} rows)`);
      setTimeout(done, 800);
    } catch (e: unknown) {
      fail(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-3 app-card p-4">
      <Input label="Dataset name" value={name} onChange={setName} required />
      <div>
        <label className="block text-sm font-medium mb-1">CSV file</label>
        <input type="file" accept=".csv" onChange={(e) => { setFile(e.target.files?.[0] || null); setPreview(null); }} />
      </div>
      <Input label="Encoding" value={encoding} onChange={(value) => { setEncoding(value); setPreview(null); }} placeholder="auto, utf-8, utf-8-sig, latin-1" />
      <Select label="AI policy" value={policy} onChange={setPolicy} options={AI_POLICIES} />
      <div className="flex flex-wrap gap-2">
        <button type="button" disabled={busy || !file} onClick={previewSchema} className="btn-ghost px-4 py-2 disabled:opacity-50">
          {busy ? "Reading..." : "Preview schema"}
        </button>
        <button disabled={busy || !preview} className="btn-primary px-4 py-2 disabled:opacity-50">
          {busy ? "Uploading..." : "Confirm and upload"}
        </button>
      </div>
      {preview ? (
        <div className="rounded border border-[var(--line-soft)] p-3">
          {preview.wide_file ? <div className="mb-3 rounded border border-[var(--warning)] p-2 text-sm text-[var(--warning)]">Wide file detected: {preview.column_count} columns. Confirm column names before upload.</div> : null}
          <div className="mb-2 text-xs text-[var(--muted)]">Encoding {preview.encoding} · {preview.column_count} columns</div>
          <div className="max-h-72 overflow-auto">
            <table className="data-table text-xs">
              <thead><tr><th>Source</th><th>Column</th><th>Type</th><th>Sample</th></tr></thead>
              <tbody>
                {preview.columns.map((column) => (
                  <tr key={column.name}>
                    <td>{column.source_name}</td>
                    <td className="font-mono">{column.name}</td>
                    <td>{column.type}</td>
                    <td className="font-mono">{JSON.stringify(column.sample)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : null}
    </form>
  );
}

function PostgresForm({ busy, setBusy, ok, fail, done }: FormProps) {
  const [form, setForm] = useState({
    name: "",
    host: "localhost",
    port: 5432,
    database: "",
    username: "",
    password: "",
    schemas: "public",
    ai_policy: "local_only",
  });

  function set<K extends keyof typeof form>(k: K, v: (typeof form)[K]) {
    setForm({ ...form, [k]: v });
  }

  async function testConn() {
    setBusy(true);
    try {
      await apiFetch("/connectors/postgres/test", {
        method: "POST",
        body: JSON.stringify({ ...form, schemas: form.schemas.split(",").map((s) => s.trim()) }),
      });
      ok("Connection ok");
    } catch (e: unknown) {
      fail(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      const data = await apiFetch<{ datasets: { name: string }[] }>("/connectors/postgres", {
        method: "POST",
        body: JSON.stringify({ ...form, schemas: form.schemas.split(",").map((s) => s.trim()) }),
      });
      ok(`Imported ${data.datasets.length} datasets`);
      setTimeout(done, 800);
    } catch (e: unknown) {
      fail(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-3 app-card p-4">
      <Input label="Connection name" value={form.name} onChange={(v) => set("name", v)} required />
      <div className="grid grid-cols-2 gap-3">
        <Input label="Host" value={form.host} onChange={(v) => set("host", v)} />
        <Input label="Port" value={String(form.port)} onChange={(v) => set("port", Number(v))} />
      </div>
      <Input label="Database" value={form.database} onChange={(v) => set("database", v)} required />
      <div className="grid grid-cols-2 gap-3">
        <Input label="Username" value={form.username} onChange={(v) => set("username", v)} required />
        <Input label="Password" value={form.password} onChange={(v) => set("password", v)} type="password" />
      </div>
      <Input label="Schemas (comma-separated)" value={form.schemas} onChange={(v) => set("schemas", v)} />
      <Select label="AI policy" value={form.ai_policy} onChange={(v) => set("ai_policy", v)} options={AI_POLICIES} />
      <div className="flex gap-2">
        <button type="button" disabled={busy} onClick={testConn} className="border px-4 py-2 rounded">
          Test
        </button>
        <button disabled={busy} className="btn-primary px-4 py-2 disabled:opacity-50">
          {busy ? "Importing..." : "Import all tables"}
        </button>
      </div>
    </form>
  );
}

function RestForm({ busy, setBusy, ok, fail, done }: FormProps) {
  const [name, setName] = useState("");
  const [datasetName, setDatasetName] = useState("");
  const [configJson, setConfigJson] = useState(
    JSON.stringify(
      {
        base_url: "https://api.example.com",
        path: "/items",
        auth: { type: "bearer_token", token: "..." },
        pagination: { type: "page", page_param: "page", page_size_param: "limit", page_size: 100, max_pages: 5 },
        response_path: "$.data",
      },
      null,
      2,
    ),
  );
  const [policy, setPolicy] = useState("cloud_allowed");

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      let config: unknown;
      try { config = JSON.parse(configJson); } catch { throw new Error("Invalid JSON config"); }
      const data = await apiFetch<{ row_count: number }>("/connectors/rest", {
        method: "POST",
        body: JSON.stringify({ name, dataset_name: datasetName, config, ai_policy: policy }),
      });
      ok(`Imported ${data.row_count} rows`);
      setTimeout(done, 800);
    } catch (e: unknown) {
      fail(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-3 app-card p-4">
      <Input label="Connector name" value={name} onChange={setName} required />
      <Input label="Dataset name" value={datasetName} onChange={setDatasetName} required />
      <div>
        <label className="block text-sm font-medium mb-1">Config (JSON)</label>
        <textarea
          className="input-dark w-full font-mono text-xs h-64"
          value={configJson}
          onChange={(e) => setConfigJson(e.target.value)}
        />
      </div>
      <Select label="AI policy" value={policy} onChange={setPolicy} options={AI_POLICIES} />
      <button disabled={busy} className="btn-primary px-4 py-2 disabled:opacity-50">
        {busy ? "Fetching..." : "Fetch and import"}
      </button>
    </form>
  );
}

function Input({ label, value, onChange, type = "text", required = false, placeholder }: {
  label: string; value: string; onChange: (v: string) => void; type?: string; required?: boolean; placeholder?: string;
}) {
  return (
    <div>
      <label className="block text-sm font-medium mb-1">{label}</label>
      <input type={type} required={required} value={value} placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        className="input-dark w-full" />
    </div>
  );
}

function Select({ label, value, onChange, options }: {
  label: string; value: string; onChange: (v: string) => void; options: string[];
}) {
  return (
    <div>
      <label className="block text-sm font-medium mb-1">{label}</label>
      <select value={value} onChange={(e) => onChange(e.target.value)}
        className="input-dark w-full">
        {options.map((o) => <option key={o} value={o}>{o}</option>)}
      </select>
    </div>
  );
}
