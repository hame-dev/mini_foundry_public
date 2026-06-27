"use client";

import Link from "next/link";
import { useEffect, useRef, type ReactNode } from "react";
import { Button } from "./controls";

/* =========================================================================
   Empty / Error / Loading states
   ========================================================================= */

export function EmptyState({
  title,
  description,
  icon,
  action,
}: {
  title: string;
  description?: string;
  icon?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="fstate">
      {icon ? <div className="fstate-icon" aria-hidden>{icon}</div> : null}
      <div className="fstate-title">{title}</div>
      {description ? <div className="fstate-help">{description}</div> : null}
      {action ? <div className="fstate-action">{action}</div> : null}
    </div>
  );
}

export function ErrorState({
  title = "Something went wrong",
  description,
  onRetry,
}: {
  title?: string;
  description?: string;
  onRetry?: () => void;
}) {
  return (
    <div className="fstate">
      <div className="fstate-icon fstate-icon-danger" aria-hidden>
        !
      </div>
      <div className="fstate-title">{title}</div>
      {description ? <div className="fstate-help">{description}</div> : null}
      {onRetry ? (
        <div className="fstate-action">
          <Button variant="secondary" size="sm" onClick={onRetry}>
            Retry
          </Button>
        </div>
      ) : null}
    </div>
  );
}

export function Skeleton({ width = "100%", height = 14, className = "" }: { width?: number | string; height?: number | string; className?: string }) {
  return <span className={`fskeleton ${className}`.trim()} style={{ width, height }} aria-hidden />;
}

export function LoadingState({ label = "Loading…", rows = 3 }: { label?: string; rows?: number }) {
  return (
    <div className="fstate" role="status" aria-live="polite">
      <div className="fstate-skeletons" aria-hidden>
        {Array.from({ length: rows }).map((_, i) => (
          <Skeleton key={i} width={`${90 - i * 12}%`} />
        ))}
      </div>
      <div className="fstate-help">{label}</div>
    </div>
  );
}

/* =========================================================================
   Breadcrumbs
   ========================================================================= */

export interface Crumb {
  label: string;
  href?: string;
}

export function Breadcrumbs({ items }: { items: Crumb[] }) {
  return (
    <nav className="fcrumbs" aria-label="Breadcrumb">
      {items.map((c, i) => {
        const last = i === items.length - 1;
        return (
          <span key={`${c.label}-${i}`} className="fcrumb">
            {i > 0 ? <span className="fcrumb-sep" aria-hidden>›</span> : null}
            {c.href && !last ? (
              <Link href={c.href}>{c.label}</Link>
            ) : (
              <span className={last ? "fcrumb-current" : undefined} aria-current={last ? "page" : undefined}>
                {c.label}
              </span>
            )}
          </span>
        );
      })}
    </nav>
  );
}

/* =========================================================================
   Dialog + ConfirmDialog (focus-trapped, Escape to close)
   ========================================================================= */

export function Dialog({
  open,
  onClose,
  title,
  children,
  footer,
  width = 480,
}: {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
  width?: number;
}) {
  const panelRef = useRef<HTMLDivElement>(null);
  const previouslyFocused = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!open) return;
    previouslyFocused.current = document.activeElement as HTMLElement | null;

    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.preventDefault();
        onClose();
        return;
      }
      if (e.key === "Tab" && panelRef.current) {
        const focusable = panelRef.current.querySelectorAll<HTMLElement>(
          'a[href],button:not([disabled]),textarea,input,select,[tabindex]:not([tabindex="-1"])',
        );
        if (focusable.length === 0) return;
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    }

    document.addEventListener("keydown", onKey);
    // Focus the first focusable element in the panel.
    const t = window.setTimeout(() => {
      panelRef.current?.querySelector<HTMLElement>(
        'a[href],button:not([disabled]),textarea,input,select,[tabindex]:not([tabindex="-1"])',
      )?.focus();
    }, 0);

    return () => {
      document.removeEventListener("keydown", onKey);
      window.clearTimeout(t);
      previouslyFocused.current?.focus?.();
    };
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="fdialog-overlay" onMouseDown={onClose} role="presentation">
      <div
        ref={panelRef}
        className="fdialog"
        style={{ maxWidth: width }}
        role="dialog"
        aria-modal="true"
        aria-label={typeof title === "string" ? title : undefined}
        onMouseDown={(e) => e.stopPropagation()}
      >
        <header className="fdialog-head">
          <div className="fdialog-title">{title}</div>
          <button type="button" className="ficon-btn" aria-label="Close dialog" onClick={onClose}>
            ✕
          </button>
        </header>
        <div className="fdialog-body">{children}</div>
        {footer ? <footer className="fdialog-foot">{footer}</footer> : null}
      </div>
    </div>
  );
}

export function ConfirmDialog({
  open,
  onClose,
  onConfirm,
  title,
  message,
  confirmLabel = "Confirm",
  danger = false,
}: {
  open: boolean;
  onClose: () => void;
  onConfirm: () => void;
  title: string;
  message: ReactNode;
  confirmLabel?: string;
  danger?: boolean;
}) {
  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={title}
      footer={
        <>
          <Button variant="ghost" size="sm" onClick={onClose}>
            Cancel
          </Button>
          <Button variant={danger ? "danger" : "primary"} size="sm" onClick={onConfirm}>
            {confirmLabel}
          </Button>
        </>
      }
    >
      <div className="fdialog-message">{message}</div>
    </Dialog>
  );
}

/* =========================================================================
   Drawer (right side panel)
   ========================================================================= */

export function Drawer({
  open,
  onClose,
  title,
  children,
  width = 380,
}: {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  children: ReactNode;
  width?: number;
}) {
  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="fdrawer-overlay" onMouseDown={onClose} role="presentation">
      <aside
        className="fdrawer"
        style={{ width }}
        role="dialog"
        aria-modal="true"
        aria-label={typeof title === "string" ? title : undefined}
        onMouseDown={(e) => e.stopPropagation()}
      >
        <header className="fdrawer-head">
          <div className="fdrawer-title">{title}</div>
          <button type="button" className="ficon-btn" aria-label="Close panel" onClick={onClose}>
            ✕
          </button>
        </header>
        <div className="fdrawer-body">{children}</div>
      </aside>
    </div>
  );
}
