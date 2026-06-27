"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { CommandPalette } from "./CommandPalette";
import { API_BASE, apiFetch } from "@/lib/api";
import { BranchSelector } from "@/components/platform/BranchSelector";
import { BranchTaskbar } from "@/components/platform/BranchTaskbar";
import { ThemeToggle } from "./ThemeToggle";

type NavItem = { href: string; label: string; mark: string };
type NavGroup = { label: string; items: NavItem[] };

const navGroups: NavGroup[] = [
  {
    label: "Workspace",
    items: [
      { href: "/workspace", label: "Workspace", mark: "WS" },
      { href: "/workspace/trash", label: "Trash", mark: "TR" },
      { href: "/data/catalog", label: "Data Catalog", mark: "DA" },
      { href: "/data/sources", label: "Sources", mark: "SO" },
      { href: "/data/lineage", label: "Lineage", mark: "LG" },
    ],
  },
  {
    label: "Build",
    items: [
      { href: "/build/pipelines", label: "Pipelines", mark: "PL" },
      { href: "/build/runs", label: "Build Runs", mark: "BR" },
      { href: "/workspace/branches", label: "Branches", mark: "GB" },
      { href: "/ontology/manager", label: "Ontology", mark: "ON" },
      { href: "/ontology/explorer", label: "Object Explorer", mark: "OE" },
      { href: "/ontology/object-sets", label: "Object Sets", mark: "OS" },
      { href: "/ontology/functions", label: "Functions", mark: "FN" },
      { href: "/apps/builder", label: "App Builder", mark: "AP" },
      { href: "/apps/dashboards", label: "Dashboards", mark: "DB" },
    ],
  },
  {
    label: "Analyze and Develop",
    items: [
      { href: "/analytics/sql", label: "SQL", mark: "SQ" },
      { href: "/analytics/explore", label: "Explore", mark: "EX" },
      { href: "/analytics/quiver", label: "Quiver", mark: "QV" },
      { href: "/develop/notebooks", label: "Notebooks", mark: "NB" },
      { href: "/develop/code", label: "Code", mark: "CR" },
      { href: "/develop/models", label: "Models", mark: "ML" },
      { href: "/ai/assistant", label: "AI", mark: "AI" },
    ],
  },
  {
    label: "Govern and Operate",
    items: [
      { href: "/governance/users", label: "Users", mark: "US" },
      { href: "/governance/access-requests", label: "Access Requests", mark: "AR" },
      { href: "/governance/audit", label: "Audit", mark: "AU" },
      { href: "/operations/jobs", label: "Jobs", mark: "JB" },
      { href: "/operations/schedules", label: "Schedules", mark: "SC" },
      { href: "/operations/health", label: "Health", mark: "HL" },
      { href: "/settings/ai", label: "Settings", mark: "ST" },
      { href: "/help", label: "Help Guide", mark: "HG" },
    ],
  },
];

const ALL_ITEMS: NavItem[] = navGroups.flatMap((g) => g.items);

type Health = {
  status: string;
  checks: Record<string, { status: string; detail?: string }>;
};

type NotificationSummary = { unread: number };

function isActive(pathname: string, href: string) {
  if (href === "/data/catalog") {
    return pathname === "/" || pathname.startsWith("/data/catalog") || pathname.startsWith("/catalog");
  }
  return pathname === href || pathname.startsWith(`${href}/`);
}

function titleCase(s: string) {
  if (/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(s)) {
    return `${s.slice(0, 8)}…`;
  }
  return s
    .replace(/-/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

function buildBreadcrumbs(pathname: string) {
  const parts = pathname.split("/").filter(Boolean);
  if (parts.length === 0) return [{ href: "/workspace", label: "Workspace", current: true }];

  const crumbs: { href: string; label: string; current: boolean }[] = [];
  let acc = "";
  parts.forEach((part, i) => {
    acc += `/${part}`;
    const last = i === parts.length - 1;
    // Skip the "admin" segment as a clickable crumb — it's a section folder.
    if (part === "admin") {
      crumbs.push({ href: acc, label: "Admin", current: false });
      return;
    }
    crumbs.push({
      href: acc,
      label: titleCase(decodeURIComponent(part)),
      current: last,
    });
  });
  return crumbs;
}

function workspaceTitle(pathname: string): { kicker: string; title: string } {
  const match = ALL_ITEMS.find((i) => isActive(pathname, i.href));
  if (match) {
    const group = navGroups.find((g) => g.items.some((it) => it.href === match.href));
    return { kicker: group?.label ?? "Workspace", title: match.label };
  }
  return { kicker: "Workspace", title: "Mini Foundry" };
}

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const crumbs = buildBreadcrumbs(pathname);
  const ws = workspaceTitle(pathname);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [health, setHealth] = useState<Health | null>(null);
  const [userEmail, setUserEmail] = useState<string | null>(null);
  const [userRoles, setUserRoles] = useState<string[]>([]);
  const [sessionResolved, setSessionResolved] = useState(false);
  const [notificationSummary, setNotificationSummary] = useState<NotificationSummary | null>(null);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const mod = e.metaKey || e.ctrlKey;
      if (mod && (e.key === "k" || e.key === "K")) {
        e.preventDefault();
        setPaletteOpen((v) => !v);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  useEffect(() => {
    if (!userEmail) return;
    let cancelled = false;
    let source: EventSource | null = null;
    async function loadNotifications() {
      try {
        const data = await apiFetch<NotificationSummary>("/notifications/summary", { cache: "no-store" });
        if (!cancelled) setNotificationSummary(data);
      } catch {
        if (!cancelled) setNotificationSummary({ unread: 0 });
      }
    }
    loadNotifications();
    if (typeof EventSource !== "undefined") {
      source = new EventSource(`${API_BASE}/notifications/stream`, { withCredentials: true });
      source.addEventListener("summary", (event) => {
        try {
          const data = JSON.parse((event as MessageEvent).data) as NotificationSummary;
          if (!cancelled) setNotificationSummary(data);
        } catch {
          // Ignore malformed stream events; polling remains active.
        }
      });
    }
    const id = window.setInterval(loadNotifications, 30000);
    return () => {
      cancelled = true;
      source?.close();
      window.clearInterval(id);
    };
  }, [userEmail]);

  useEffect(() => {
    let cancelled = false;
    apiFetch<{ email: string; roles?: string[] }>("/auth/me")
      .then((u) => {
        if (!cancelled) {
          setUserEmail(u.email);
          setUserRoles(u.roles ?? []);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setUserEmail(null);
          setUserRoles([]);
        }
      })
      .finally(() => {
        if (!cancelled) setSessionResolved(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!sessionResolved || userEmail) return;
    if (pathname.startsWith("/login") || pathname.startsWith("/callback")) return;
    window.location.href = "/login";
  }, [pathname, sessionResolved, userEmail]);

  async function logout() {
    await apiFetch("/auth/logout", { method: "POST" }).catch(() => null);
    window.location.href = "/login";
  }

  useEffect(() => {
    let cancelled = false;
    async function loadHealth() {
      try {
        const data = await apiFetch<Health>("/system/health", { cache: "no-store" });
        if (!cancelled) setHealth(data);
      } catch {
        if (!cancelled) setHealth({ status: "degraded", checks: { api: { status: "error" } } });
      }
    }
    loadHealth();
    const id = window.setInterval(loadHealth, 30000);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, []);

  if (!sessionResolved) {
    return <div className="app-shell"><main className="app-content">Checking session...</main></div>;
  }
  if (!userEmail && !pathname.startsWith("/login") && !pathname.startsWith("/callback")) {
    return <div className="app-shell"><main className="app-content">Redirecting...</main></div>;
  }
  const isAdmin = userRoles.includes("admin");
  const visibleNavGroups = navGroups.map((group) => ({
    ...group,
    items: group.items.filter((item) => isAdmin || !item.href.startsWith("/governance/users")),
  }));

  return (
    <div className="app-shell">
      <aside className="app-sidebar">
        <Link href="/data/catalog" className="brand-lockup" aria-label="Mini Foundry home">
          <span className="brand-mark">MF</span>
          <span>
            <span className="brand-name">Mini Foundry</span>
            <span className="brand-subtitle">Operational intelligence</span>
          </span>
        </Link>

        <button
          type="button"
          className="sidebar-cmd"
          aria-label="Open command palette"
          onClick={() => setPaletteOpen(true)}
        >
          <span aria-hidden>⌕</span>
          <span>Search · jump to…</span>
          <span className="kbd">⌘K</span>
        </button>

        <nav className="sidebar-nav" aria-label="Primary navigation">
          {visibleNavGroups.map((group) => (
            <section key={group.label} className="sidebar-group">
              <div className="sidebar-group-label">{group.label}</div>
              <div className="sidebar-group-items">
                {group.items.map((item) => {
                  const active = isActive(pathname, item.href);
                  return (
                    <Link
                      key={item.href}
                      href={item.href}
                      title={item.label}
                      className={`sidebar-link ${active ? "sidebar-link-active" : ""}`}
                      aria-current={active ? "page" : undefined}
                    >
                      <span className="sidebar-link-mark">{item.mark}</span>
                      <span className="sidebar-link-label">{item.label}</span>
                    </Link>
                  );
                })}
              </div>
            </section>
          ))}
        </nav>

        <div className="sidebar-footer">
          <ThemeToggle />
          <div className="status-row">
            <span className="status-dot" style={{ background: health?.status === "degraded" ? "var(--warning)" : undefined }} />
            <span>Local cluster · {health?.status ?? "checking"}</span>
          </div>
          {userEmail ? (
            <button type="button" className="sidebar-login" onClick={logout}>
              <span>{userEmail}</span>
              <span aria-hidden>Sign out</span>
            </button>
          ) : (
            <Link href="/login" className="sidebar-login">
              <span>Sign in</span>
              <span aria-hidden>→</span>
            </Link>
          )}
        </div>
      </aside>

      <div className="app-main">
        <header className="app-topbar">
          <div className="topbar-breadcrumb" style={{ minWidth: 0 }}>
            <nav className="topbar-breadcrumbs" aria-label="Breadcrumb">
          <Link href="/workspace">Mini Foundry</Link>
              {crumbs.map((c, i) => (
                <span
                  key={c.href + i}
                  style={{ display: "inline-flex", alignItems: "center", gap: 6 }}
                >
                  <span className="crumb-sep" aria-hidden>
                    ›
                  </span>
                  {c.current ? (
                    <span className="crumb-current">{c.label}</span>
                  ) : (
                    <Link href={c.href}>{c.label}</Link>
                  )}
                </span>
              ))}
            </nav>
            <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
              <span className="topbar-kicker">{ws.kicker}</span>
              <span className="topbar-title">{ws.title}</span>
            </div>
          </div>
          <div className="topbar-actions">
            <BranchSelector />
            <Link href="/notifications" className="topbar-pill" title="Notifications">
              Alerts · {notificationSummary?.unread ?? 0}
            </Link>
            {["postgres", "redis", "trino", "spark", "ai"].map((name) => {
              const state = health?.checks?.[name]?.status ?? "checking";
              const dotClass =
                state === "ok" || state === "healthy" ? "topbar-pill-ok"
                  : state === "checking" ? "topbar-pill-checking"
                    : "topbar-pill-degraded";
              return (
                <span key={name} className={`topbar-pill ${dotClass}`} title={health?.checks?.[name]?.detail || state}>
                  {name} · {state}
                </span>
              );
            })}
          </div>
        </header>
        <main className="app-content">
          <BranchTaskbar />
          {children}
        </main>
      </div>
      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} />
    </div>
  );
}
