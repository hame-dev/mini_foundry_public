"use client";

import Link from "next/link";
import { useEffect, useState, type ReactNode } from "react";
import { StatusPill } from "./controls";

export function ResourceHeader({
  eyebrow,
  title,
  subtitle,
  status,
  meta,
  tabs = [],
  activeTab,
  onTabChange,
  actions,
}: {
  eyebrow?: string;
  title: string;
  subtitle?: string;
  /** Real resource status (drives the StatusPill). Omit to show no pill. */
  status?: string;
  /** Optional meta chips rendered under the title (branch, version, markings…). */
  meta?: ReactNode;
  tabs?: Array<{ label: string; href?: string; id?: string }>;
  activeTab?: string;
  onTabChange?: (tab: string) => void;
  actions?: ReactNode;
}) {
  const [selectedTab, setSelectedTab] = useState(activeTab ?? tabs[0]?.id ?? tabs[0]?.label ?? "");

  useEffect(() => {
    if (activeTab) setSelectedTab(activeTab);
  }, [activeTab]);

  return (
    <section className="foundry-resource-header">
      <div className="foundry-resource-main">
        {eyebrow ? <div className="foundry-eyebrow">{eyebrow}</div> : null}
        <div className="foundry-resource-title-row">
          <h1 className="foundry-resource-title">{title}</h1>
          {status ? <StatusPill status={status} /> : null}
        </div>
        {subtitle ? <p className="foundry-resource-subtitle">{subtitle}</p> : null}
        {meta ? <div className="foundry-resource-meta">{meta}</div> : null}
      </div>
      <div className="foundry-resource-actions">{actions}</div>
      {tabs.length ? (
        <nav className="foundry-tabs">
          {tabs.map((tab) => {
            const key = tab.id ?? tab.label;
            const selected = selectedTab === key;
            const className = `foundry-tab ${selected ? "foundry-tab-active" : ""}`;
            return tab.href ? (
              <Link key={tab.label} href={tab.href} className={className}>{tab.label}</Link>
            ) : !onTabChange ? (
              <span
                key={tab.label}
                className={className}
                aria-disabled={!selected}
                style={!selected ? { cursor: "default", opacity: 0.55 } : { cursor: "default" }}
              >
                {tab.label}
              </span>
            ) : (
              <button
                key={tab.label}
                className={className}
                type="button"
                onClick={() => {
                  setSelectedTab(key);
                  onTabChange?.(key);
                }}
              >
                {tab.label}
              </button>
            );
          })}
        </nav>
      ) : null}
    </section>
  );
}

export function ResourceToolbar({ children }: { children: ReactNode }) {
  return <div className="foundry-toolbar">{children}</div>;
}

export function RightInspector({ title, children }: { title: string; children: ReactNode }) {
  return (
    <aside className="foundry-right-panel">
      <div className="panel-heading">{title}</div>
      <div className="foundry-right-panel-body">{children}</div>
    </aside>
  );
}

export function BottomDrawer({
  title,
  tabs,
  active,
  children,
}: {
  title: string;
  tabs?: string[];
  active?: string;
  children: ReactNode;
}) {
  const [selectedTab, setSelectedTab] = useState(active ?? tabs?.[0] ?? "");
  useEffect(() => {
    if (active) setSelectedTab(active);
  }, [active]);
  return (
    <section className="foundry-bottom-drawer">
      <div className="foundry-bottom-title">
        <strong>{title}</strong>
        {tabs?.map((tab) => (
          <button
            key={tab}
            type="button"
            className={`badge ${selectedTab === tab ? "badge-accent" : ""}`}
            onClick={() => setSelectedTab(tab)}
          >
            {tab}
          </button>
        ))}
      </div>
      <div className="foundry-bottom-body">{children}</div>
    </section>
  );
}

export function ModuleCard({
  title,
  subtitle,
  icon,
  children,
}: {
  title: string;
  subtitle?: string;
  icon?: string;
  children?: ReactNode;
}) {
  return (
    <section className="foundry-module-card">
      <div className="foundry-module-art" aria-hidden>
        <span>{icon ?? "□"}</span>
      </div>
      <div className="foundry-module-body">
        <h3>{title}</h3>
        {subtitle ? <p>{subtitle}</p> : null}
        {children}
      </div>
    </section>
  );
}

export function EmptyPanel({ title, body }: { title: string; body: string }) {
  return (
    <div className="empty-state">
      <div className="empty-state-title">{title}</div>
      <div className="empty-state-help">{body}</div>
    </div>
  );
}
