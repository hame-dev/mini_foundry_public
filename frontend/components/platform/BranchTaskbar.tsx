"use client";

import Link from "next/link";
import { useActiveBranch } from "@/lib/branchContext";

export function BranchTaskbar() {
  const { branchName, setBranchName } = useActiveBranch();
  return (
    <div className="app-card" style={{ padding: "8px 12px", marginBottom: 12, display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0 }}>
        <span className="text-sm text-[var(--muted)]">Editing context</span>
        <input
          className="input-dark h-8 w-44 text-xs font-mono"
          value={branchName}
          onChange={(event) => setBranchName(event.target.value)}
          aria-label="Active branch editing context"
        />
        <span className="badge">{branchName === "main" ? "production" : "branch draft"}</span>
      </div>
      <Link className="topbar-pill" href="/workspace/branches">Review branches</Link>
    </div>
  );
}
