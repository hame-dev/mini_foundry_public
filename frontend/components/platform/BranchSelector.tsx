"use client";

import { useActiveBranch } from "@/lib/branchContext";

export function BranchSelector() {
  const { branchName, setBranchName } = useActiveBranch();
  return (
    <label className="topbar-pill" style={{ gap: 6 }}>
      <span>Branch</span>
      <select
        aria-label="Active branch"
        value={branchName}
        onChange={(event) => setBranchName(event.target.value)}
        style={{ background: "transparent", color: "inherit", border: 0 }}
      >
        <option value="main">main</option>
        {branchName !== "main" ? <option value={branchName}>{branchName}</option> : null}
      </select>
    </label>
  );
}
