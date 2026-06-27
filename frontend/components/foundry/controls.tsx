"use client";

import {
  forwardRef,
  type ButtonHTMLAttributes,
  type InputHTMLAttributes,
  type ReactNode,
  type SelectHTMLAttributes,
} from "react";
import { statusTone, toneBadgeClass, type StatusTone } from "@/lib/status";

/* =========================================================================
   Button + IconButton
   ========================================================================= */

type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";
type ButtonSize = "sm" | "md";

const VARIANT_CLASS: Record<ButtonVariant, string> = {
  primary: "fbtn-primary",
  secondary: "fbtn-secondary",
  ghost: "fbtn-ghost",
  danger: "fbtn-danger",
};

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  loading?: boolean;
  leadingIcon?: ReactNode;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "secondary", size = "md", loading = false, leadingIcon, className = "", children, disabled, ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      className={`fbtn ${VARIANT_CLASS[variant]} ${size === "sm" ? "fbtn-sm" : ""} ${className}`.trim()}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      {...rest}
    >
      {loading ? <span className="fbtn-spinner" aria-hidden /> : leadingIcon}
      {children}
    </button>
  );
});

export interface IconButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  label: string;
}

export const IconButton = forwardRef<HTMLButtonElement, IconButtonProps>(function IconButton(
  { label, className = "", children, ...rest },
  ref,
) {
  return (
    <button ref={ref} className={`ficon-btn ${className}`.trim()} aria-label={label} title={label} {...rest}>
      {children}
    </button>
  );
});

/* =========================================================================
   Badge + StatusPill
   ========================================================================= */

export function Badge({
  tone = "neutral",
  className = "",
  children,
}: {
  tone?: StatusTone;
  className?: string;
  children: ReactNode;
}) {
  return <span className={`badge ${toneBadgeClass(tone)} ${className}`.trim()}>{children}</span>;
}

export function StatusPill({ status, tone }: { status: string; tone?: StatusTone }) {
  const resolved = tone ?? statusTone(status);
  return (
    <span className={`status-pill ${toneBadgeClass(resolved)}`.trim()}>
      <span className="status-pill-dot" aria-hidden />
      {status}
    </span>
  );
}

/* =========================================================================
   Card
   ========================================================================= */

export function Card({
  title,
  actions,
  footer,
  className = "",
  bodyClassName = "",
  children,
}: {
  title?: ReactNode;
  actions?: ReactNode;
  footer?: ReactNode;
  className?: string;
  bodyClassName?: string;
  children: ReactNode;
}) {
  return (
    <section className={`fcard ${className}`.trim()}>
      {title || actions ? (
        <header className="fcard-head">
          <div className="fcard-title">{title}</div>
          {actions ? <div className="fcard-actions">{actions}</div> : null}
        </header>
      ) : null}
      <div className={`fcard-body ${bodyClassName}`.trim()}>{children}</div>
      {footer ? <footer className="fcard-foot">{footer}</footer> : null}
    </section>
  );
}

/* =========================================================================
   Tabs (controlled)
   ========================================================================= */

export interface TabItem {
  id: string;
  label: ReactNode;
}

export function Tabs({
  tabs,
  active,
  onChange,
}: {
  tabs: TabItem[];
  active: string;
  onChange: (id: string) => void;
}) {
  return (
    <nav className="ftabs" role="tablist">
      {tabs.map((tab) => {
        const selected = tab.id === active;
        return (
          <button
            key={tab.id}
            type="button"
            role="tab"
            aria-selected={selected}
            className={`ftab ${selected ? "ftab-active" : ""}`.trim()}
            onClick={() => onChange(tab.id)}
          >
            {tab.label}
          </button>
        );
      })}
    </nav>
  );
}

/* =========================================================================
   Form controls
   ========================================================================= */

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(function Input(
  { className = "", ...rest },
  ref,
) {
  return <input ref={ref} className={`input-dark ${className}`.trim()} {...rest} />;
});

export const Select = forwardRef<HTMLSelectElement, SelectHTMLAttributes<HTMLSelectElement>>(function Select(
  { className = "", children, ...rest },
  ref,
) {
  return (
    <select ref={ref} className={`input-dark ${className}`.trim()} {...rest}>
      {children}
    </select>
  );
});

export function Field({
  label,
  htmlFor,
  hint,
  error,
  children,
}: {
  label: string;
  htmlFor?: string;
  hint?: string;
  error?: string;
  children: ReactNode;
}) {
  return (
    <div className="ffield">
      <label className="ffield-label" htmlFor={htmlFor}>
        {label}
      </label>
      {children}
      {error ? (
        <span className="ffield-error">{error}</span>
      ) : hint ? (
        <span className="ffield-hint">{hint}</span>
      ) : null}
    </div>
  );
}
