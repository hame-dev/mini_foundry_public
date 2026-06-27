"use client";

import dynamic from "next/dynamic";
import { use, useEffect, useMemo, useState } from "react";
import { apiFetch } from "@/lib/api";
import type { CodeRepositoryFile, CodeRepositorySummary } from "@/lib/types";
import { BottomDrawer, ResourceHeader, ResourceToolbar, RightInspector } from "@/components/foundry/FoundryPrimitives";

const MonacoEditor = dynamic(() => import("@monaco-editor/react"), { ssr: false });

type FileMap = Record<string, string>;
type TestResult = { name: string; status: "passed" | "failed" | "error"; message?: string };

export default function CodeRepositoryDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const [repo, setRepo] = useState<CodeRepositorySummary | null>(null);
  const [files, setFiles] = useState<CodeRepositoryFile[]>([]);
  const [contents, setContents] = useState<FileMap>({});
  const [activeFile, setActiveFile] = useState<string>("");
  const [testResults, setTestResults] = useState<TestResult[] | null>(null);
  const [output, setOutput] = useState<any | null>(null);
  const [log, setLog] = useState<any[]>([]);
  const [branches, setBranches] = useState<string[]>([]);
  const [prs, setPrs] = useState<any[]>([]);
  const [diff, setDiff] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [activeTab, setActiveTab] = useState("Code");
  const [dirty, setDirty] = useState<Record<string, boolean>>({});

  const activeContent = contents[activeFile] ?? "";
  const language = activeFile.endsWith(".py") ? "python" : activeFile.endsWith(".sql") ? "sql" : "plaintext";

  async function openFile(path: string) {
    setActiveFile(path);
    if (contents[path] !== undefined) return;
    const result = await apiFetch<{ path: string; content: string }>(`/code-repo/repositories/${id}/files/content?path=${encodeURIComponent(path)}`);
    setContents((prev) => ({ ...prev, [path]: result.content }));
  }

  async function load() {
    const [repoRow, fileRows, gitRows, branchRows, prRows, diffRow] = await Promise.all([
      apiFetch<CodeRepositorySummary>(`/code-repo/repositories/${id}`),
      apiFetch<CodeRepositoryFile[]>(`/code-repo/repositories/${id}/files`),
      apiFetch<any[]>(`/code-repo/${id}/git/log`).catch(() => []),
      apiFetch<string[]>(`/code-repo/${id}/git/branches`).catch(() => []),
      apiFetch<any[]>(`/code-repo/${id}/pull-requests`).catch(() => []),
      apiFetch<{ diff: string }>(`/code-repo/${id}/git/diff`).catch(() => ({ diff: "" })),
    ]);
    setRepo(repoRow);
    setFiles(fileRows);
    setLog(gitRows);
    setBranches(branchRows);
    setPrs(prRows);
    setDiff(diffRow.diff);
    await apiFetch("/activity/track", {
      method: "POST",
      body: JSON.stringify({ resource_type: "code_repository", resource_id: id, title: repoRow.name, path: `/code-repo/${id}` }),
    }).catch(() => {});
    if (fileRows[0]) await openFile(fileRows[0].path);
  }

  useEffect(() => {
    load().catch((e) => setError(e.message));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  function updateActiveFile(value: string) {
    setContents((prev) => ({ ...prev, [activeFile]: value }));
    if (activeFile) setDirty((prev) => ({ ...prev, [activeFile]: true }));
  }

  async function saveFile() {
    if (!activeFile) return;
    await apiFetch(`/code-repo/repositories/${id}/files/content`, {
      method: "PUT",
      body: JSON.stringify({ path: activeFile, content: activeContent }),
    });
    setDirty((prev) => ({ ...prev, [activeFile]: false }));
    await load();
  }

  async function addFile() {
    const path = prompt("New file path", "src/transform.py");
    if (!path) return;
    setFiles((prev) => [...prev, { path, size: 0, language: path.split(".").pop() ?? "text" }]);
    setContents((prev) => ({ ...prev, [path]: `# ${path}\n` }));
    setActiveFile(path);
  }

  async function addFolder() {
    const path = prompt("New folder path", "src/new_folder");
    if (!path) return;
    await apiFetch(`/code-repo/repositories/${id}/folders`, { method: "POST", body: JSON.stringify({ path }) });
    await load();
  }

  async function createStarterFiles() {
    const starter: Record<string, string> = {
      "README.md": `# ${repo?.name ?? "Repository"}\n\nPython transform repository.\n`,
      "src/transform.py": "def transform(input_df):\n    return input_df\n",
      "tests/test_transform.py": "import pandas as pd\n\nfrom src.transform import transform\n\n\ndef test_transform_returns_rows():\n    assert len(transform(pd.DataFrame([{\"value\": 1}]))) == 1\n",
    };
    for (const [path, content] of Object.entries(starter)) {
      await apiFetch(`/code-repo/repositories/${id}/files/content`, { method: "PUT", body: JSON.stringify({ path, content }) });
    }
    await load();
  }

  async function commit() {
    const message = prompt("Commit message", "Update repository files");
    if (!message) return;
    await saveFile();
    await apiFetch(`/code-repo/${id}/git/commit`, {
      method: "POST",
      body: JSON.stringify({ files: contents, message }),
    });
    const gitRows = await apiFetch<any[]>(`/code-repo/${id}/git/log`).catch(() => []);
    setLog(gitRows);
  }

  async function pollJob(jobId: string): Promise<any> {
    // Code execution runs in the worker sandbox; poll until the job is terminal.
    for (let i = 0; i < 150; i++) {
      const job = await apiFetch<any>(`/jobs/${jobId}`);
      if (["succeeded", "failed", "canceled", "cancelled"].includes(job.status)) {
        return job;
      }
      await new Promise((r) => setTimeout(r, 2000));
    }
    throw new Error("Timed out waiting for job to finish.");
  }

  async function runTests() {
    setRunning(true);
    setError(null);
    try {
      await saveFile();
      const testFile = Object.keys(contents).find((f) => f.startsWith("test_") || f.includes("/test_"));
      if (!testFile) {
        setError("No test file loaded. Create tests/test_transform.py to run tests.");
        return;
      }
      const { job_id } = await apiFetch<{ job_id: string }>("/code-repo/test", {
        method: "POST",
        body: JSON.stringify({ files: contents, test_file: testFile }),
      });
      const job = await pollJob(job_id);
      if (job.status !== "succeeded") {
        setError(job.error || "Test run failed.");
        setTestResults([]);
      } else {
        setTestResults(job.output?.results || []);
      }
    } catch (e: any) {
      setError(e.message || String(e));
    } finally {
      setRunning(false);
    }
  }

  async function runTransform() {
    setRunning(true);
    setError(null);
    try {
      await saveFile();
      const { job_id } = await apiFetch<{ job_id: string }>("/code-repo/run", {
        method: "POST",
        body: JSON.stringify({ files: contents, requirements: [] }),
      });
      const job = await pollJob(job_id);
      if (job.status !== "succeeded") {
        setError(job.error || "Build failed.");
      } else {
        setOutput(job.output);
      }
    } catch (e: any) {
      setError(e.message || String(e));
    } finally {
      setRunning(false);
    }
  }

  const tabs = useMemo(() => Object.keys(contents), [contents]);

  return (
    <div style={{ display: "grid", gap: 10 }}>
      <ResourceHeader
        eyebrow="Code Repositories"
        title={repo?.name ?? "Repository"}
        subtitle={repo?.description ?? "Git-backed code authoring workspace."}
        tabs={[{ label: "Code", id: "Code" }, { label: "Branches", id: "Branches" }, { label: "Pull Requests", id: "Pull Requests" }, { label: "More", id: "More" }]}
        activeTab={activeTab}
        onTabChange={setActiveTab}
        actions={
          <>
            <button className="btn-ghost" onClick={saveFile} disabled={!activeFile}>Save file{activeFile && dirty[activeFile] ? " *" : ""}</button>
            <button className="btn-ghost" onClick={runTests} disabled={running}>Test</button>
            <button className="btn-ghost" onClick={commit}>Commit</button>
            <button className="btn-primary" onClick={runTransform} disabled={running}>Build</button>
          </>
        }
      />
      <ResourceToolbar>
        <button className="btn-ghost" onClick={addFile}>New file</button>
        <button className="btn-ghost" onClick={addFolder}>New folder</button>
        <button className="btn-ghost" onClick={() => apiFetch(`/code-repo/${id}/pull-requests`, { method: "POST", body: JSON.stringify({ title: "Proposed changes", source_branch: "main", target_branch: "main" }) }).catch((e) => setError(e.message))}>Propose changes</button>
        <span className="badge badge-success">{testResults?.filter((t) => t.status === "passed").length ?? 0} passed</span>
        {error ? <span className="badge badge-danger">{error}</span> : null}
      </ResourceToolbar>

      {activeTab === "Branches" ? (
        <main className="app-card" style={{ padding: 12 }}>
          <div className="panel-heading" style={{ padding: "0 0 8px", border: 0 }}>Branches</div>
          {branches.map((b) => <span key={b} className="badge" style={{ marginRight: 6 }}>{b}</span>)}
          <button className="btn-ghost" onClick={() => { const branch_name = prompt("Branch name", "feature/work"); if (branch_name) apiFetch(`/code-repo/${id}/git/branches`, { method: "POST", body: JSON.stringify({ branch_name, from_branch: repo?.default_branch ?? "main" }) }).then(load).catch((e) => setError(e.message)); }}>Create branch</button>
        </main>
      ) : activeTab === "Pull Requests" ? (
        <main className="app-card" style={{ padding: 12 }}>
          <div className="panel-heading" style={{ padding: "0 0 8px", border: 0 }}>Pull Requests</div>
          {prs.map((pr) => <a key={pr.id} className="btn-ghost" href={`/code-repo/pr/${pr.id}`}>{pr.title} · {pr.status}</a>)}
          {!prs.length ? <div className="empty-state"><div className="empty-state-title">No pull requests yet.</div></div> : null}
        </main>
      ) : activeTab === "More" ? (
        <main className="app-card" style={{ padding: 12, display: "grid", gap: 12 }}>
          <pre>{JSON.stringify(repo, null, 2)}</pre>
          <pre>{diff || "No working tree diff."}</pre>
          {log.map((entry) => <div key={entry.sha} style={{ fontSize: 12 }}><b>{entry.short_sha}</b> {entry.message}</div>)}
        </main>
      ) : (
      <div className="foundry-workbench" style={{ gridTemplateColumns: "260px minmax(0, 1fr) 300px" }}>
        <aside className="app-card" style={{ padding: 0, overflow: "hidden" }}>
          <div className="panel-heading">Files</div>
          <div style={{ maxHeight: "calc(100vh - 380px)", overflow: "auto" }}>
            {files.map((file) => (
              <button key={file.path} onClick={() => openFile(file.path)} style={{ width: "100%", textAlign: "left", padding: "8px 10px", border: 0, borderBottom: "1px solid var(--line-soft)", background: activeFile === file.path ? "var(--accent-soft)" : "transparent", fontFamily: "var(--font-mono)", fontSize: 12 }}>
                {file.path}
              </button>
            ))}
            {files.length === 0 ? <button className="btn-primary" style={{ margin: 10 }} onClick={createStarterFiles}>Create starter files</button> : null}
          </div>
        </aside>

        <main className="app-card" style={{ padding: 0, overflow: "hidden", minHeight: 560 }}>
          <div style={{ display: "flex", borderBottom: "1px solid var(--line)", background: "#f7f9fc", overflowX: "auto" }}>
            {tabs.map((tab) => (
              <button key={tab} onClick={() => setActiveFile(tab)} className={activeFile === tab ? "foundry-tab foundry-tab-active" : "foundry-tab"} style={{ padding: "0 12px" }}>{tab}{dirty[tab] ? " *" : ""}</button>
            ))}
          </div>
          <div style={{ height: 520 }}>
            <MonacoEditor
              height="100%"
              language={language}
              value={activeContent}
              onChange={(v) => updateActiveFile(v ?? "")}
              theme="vs-light"
              options={{ minimap: { enabled: false }, fontSize: 13, scrollBeyondLastLine: false }}
            />
          </div>
        </main>

        <RightInspector title="Repository">
          <div><span className="stat-label">Branch</span><div className="stat-value">{repo?.default_branch ?? "main"}</div></div>
          <div><span className="stat-label">Type</span><div className="stat-value">{repo?.repo_type.replace(/_/g, " ")}</div></div>
          <div className="panel-heading" style={{ padding: "8px 0", border: 0 }}>Recent commits</div>
          {log.slice(0, 5).map((entry) => <div key={entry.sha} style={{ fontSize: 12 }}><b>{entry.short_sha}</b> {entry.message}</div>)}
        </RightInspector>
      </div>
      )}

      <BottomDrawer title="Workbench" tabs={["Problems", "Debugger", "Preview", "Tests", "File Changes", "Build", "Docs", "SQL"]} active={testResults ? "Tests" : output ? "Build" : "Preview"}>
        {testResults ? <pre>{JSON.stringify(testResults, null, 2)}</pre> : output ? <pre>{JSON.stringify(output, null, 2)}</pre> : <div style={{ color: "var(--muted)" }}>Run tests or build to populate the workbench drawer.</div>}
      </BottomDrawer>
    </div>
  );
}
