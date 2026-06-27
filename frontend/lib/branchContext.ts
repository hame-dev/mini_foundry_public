"use client";

import { useCallback, useEffect, useState } from "react";

const ACTIVE_BRANCH_KEY = "mini_foundry.active_branch";

export function readActiveBranch(): string {
  if (typeof window === "undefined") return "main";
  return window.localStorage.getItem(ACTIVE_BRANCH_KEY) || "main";
}

export function writeActiveBranch(branchName: string) {
  if (typeof window === "undefined") return;
  const next = branchName.trim() || "main";
  window.localStorage.setItem(ACTIVE_BRANCH_KEY, next);
  window.dispatchEvent(new CustomEvent("mini-foundry:branch-change", { detail: next }));
}

export function useActiveBranch() {
  const [branchName, setBranchNameState] = useState("main");

  useEffect(() => {
    setBranchNameState(readActiveBranch());
    const onStorage = (event: StorageEvent) => {
      if (event.key === ACTIVE_BRANCH_KEY) setBranchNameState(event.newValue || "main");
    };
    const onBranchChange = (event: Event) => {
      setBranchNameState((event as CustomEvent<string>).detail || readActiveBranch());
    };
    window.addEventListener("storage", onStorage);
    window.addEventListener("mini-foundry:branch-change", onBranchChange);
    return () => {
      window.removeEventListener("storage", onStorage);
      window.removeEventListener("mini-foundry:branch-change", onBranchChange);
    };
  }, []);

  const setBranchName = useCallback((next: string) => {
    const value = next.trim() || "main";
    setBranchNameState(value);
    writeActiveBranch(value);
  }, []);

  return { branchName, setBranchName };
}
