/**
 * Shared UI primitives.
 *
 * Semantic elements throughout: buttons are <button>, tables are <table>, and
 * anything interactive is focusable. Styling is Tailwind against the tokens in
 * globals.css — no glass, glow, or gradient utilities.
 */

import type { ButtonHTMLAttributes, HTMLAttributes, InputHTMLAttributes, ReactNode, Ref, SelectHTMLAttributes, TableHTMLAttributes } from "react";
import { cn } from "@/lib/utils";
import { Icon, type IconName } from "./Icon";

/* ------------------------------------------------------------------ Panel */

export function Panel({ className, ...rest }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "rounded-[6px] border border-line bg-surface-raised",
        className,
      )}
      {...rest}
    />
  );
}

export function PanelHeader({
  title,
  description,
  actions,
  className,
}: {
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex flex-wrap items-start justify-between gap-3 border-b border-line-subtle px-4 py-3",
        className,
      )}
    >
      <div className="min-w-0">
        <h2 className="truncate text-[13px] font-semibold text-content">{title}</h2>
        {description ? (
          <p className="mt-0.5 text-[12px] leading-snug text-content-muted">{description}</p>
        ) : null}
      </div>
      {actions ? <div className="flex shrink-0 items-center gap-2">{actions}</div> : null}
    </div>
  );
}

export function PanelBody({ className, ...rest }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("p-4", className)} {...rest} />;
}

/* ----------------------------------------------------------------- Button */

type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";
type ButtonSize = "sm" | "md";

const BUTTON_VARIANTS: Record<ButtonVariant, string> = {
  primary:
    "bg-accent-dim text-content border border-accent/50 hover:bg-accent/25 hover:border-accent",
  secondary:
    "bg-surface-overlay text-content border border-line-strong hover:bg-surface-hover",
  ghost:
    "bg-transparent text-content-muted border border-transparent hover:bg-surface-overlay hover:text-content",
  danger:
    "bg-critical-wash text-critical border border-critical/40 hover:bg-critical/20 hover:border-critical",
};

const BUTTON_SIZES: Record<ButtonSize, string> = {
  sm: "h-7 px-2.5 text-[12px] gap-1.5",
  md: "h-9 px-3.5 text-[13px] gap-2",
};

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  icon?: IconName;
  loading?: boolean;
  /** React 19 passes ref as an ordinary prop; no forwardRef wrapper needed. */
  ref?: Ref<HTMLButtonElement>;
}

export function Button({
  variant = "secondary",
  size = "md",
  icon,
  loading = false,
  disabled,
  className,
  children,
  ref,
  ...rest
}: ButtonProps) {
  return (
    <button
      ref={ref}
      type="button"
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={cn(
        "inline-flex items-center justify-center rounded-[5px] font-medium transition-colors",
        "disabled:cursor-not-allowed disabled:opacity-45",
        BUTTON_VARIANTS[variant],
        BUTTON_SIZES[size],
        className,
      )}
      {...rest}
    >
      {loading ? (
        <Icon name="refresh" size={size === "sm" ? 13 : 15} className="animate-spin" />
      ) : icon ? (
        <Icon name={icon} size={size === "sm" ? 13 : 15} />
      ) : null}
      {children}
    </button>
  );
}

/* ------------------------------------------------------------------- Chip */

type Tone = "neutral" | "accent" | "nominal" | "warning" | "critical";

const TONE_STYLES: Record<Tone, string> = {
  neutral: "bg-neutral-wash text-content-muted border-line-strong",
  accent: "bg-accent-wash text-accent-bright border-accent-dim",
  nominal: "bg-nominal-wash text-nominal border-nominal/35",
  warning: "bg-warning-wash text-warning border-warning/35",
  critical: "bg-critical-wash text-critical border-critical/35",
};

export function Chip({
  tone = "neutral",
  className,
  children,
  ...rest
}: HTMLAttributes<HTMLSpanElement> & { tone?: Tone }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-[4px] border px-1.5 py-0.5 text-[11px] font-medium leading-tight whitespace-nowrap",
        TONE_STYLES[tone],
        className,
      )}
      {...rest}
    >
      {children}
    </span>
  );
}

/* ------------------------------------------------------------- Field/Input */

export function Field({
  label,
  hint,
  error,
  htmlFor,
  children,
}: {
  label: string;
  hint?: string;
  error?: string;
  htmlFor: string;
  children: ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={htmlFor} className="text-[12px] font-medium text-content-muted">
        {label}
      </label>
      {children}
      {error ? (
        <p role="alert" className="text-[12px] text-critical">
          {error}
        </p>
      ) : hint ? (
        <p className="text-[12px] text-content-dim">{hint}</p>
      ) : null}
    </div>
  );
}

const CONTROL_BASE =
  "w-full rounded-[5px] border border-line-strong bg-surface-sunken px-2.5 py-2 text-[13px] text-content " +
  "transition-colors placeholder:text-content-dim hover:border-line-strong/80 " +
  "focus:border-accent focus:outline-none focus-visible:outline-2 focus-visible:outline-accent-bright focus-visible:outline-offset-1 " +
  "disabled:cursor-not-allowed disabled:opacity-50";

export function Input({ className, ...rest }: InputHTMLAttributes<HTMLInputElement>) {
  return <input className={cn(CONTROL_BASE, className)} {...rest} />;
}

export function Select({ className, children, ...rest }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select className={cn(CONTROL_BASE, "cursor-pointer", className)} {...rest}>
      {children}
    </select>
  );
}

/* ------------------------------------------------------------------ Table */

export function Table({ className, children, ...rest }: TableHTMLAttributes<HTMLTableElement>) {
  return (
    <div className="w-full overflow-x-auto">
      <table className={cn("w-full border-collapse text-[13px]", className)} {...rest}>
        {children}
      </table>
    </div>
  );
}

export function Th({ className, children, ...rest }: HTMLAttributes<HTMLTableCellElement>) {
  return (
    <th
      scope="col"
      className={cn(
        "border-b border-line px-3 py-2 text-left text-[11px] font-semibold text-content-dim",
        className,
      )}
      {...rest}
    >
      {children}
    </th>
  );
}

export function Td({ className, children, ...rest }: HTMLAttributes<HTMLTableCellElement>) {
  return (
    <td className={cn("border-b border-line-subtle px-3 py-2.5 align-middle", className)} {...rest}>
      {children}
    </td>
  );
}

/* ------------------------------------------------------------------- Misc */

/** Monospace run for IDs, timestamps, coordinates, and telemetry values. */
export function Mono({ className, children, ...rest }: HTMLAttributes<HTMLSpanElement>) {
  return (
    <span className={cn("font-mono text-[12px] tabular", className)} {...rest}>
      {children}
    </span>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("sg-skeleton h-4 w-full", className)} aria-hidden="true" />;
}

export function PageHeader({
  title,
  description,
  actions,
}: {
  title: string;
  description?: string;
  actions?: ReactNode;
}) {
  return (
    <header className="mb-5 flex flex-wrap items-start justify-between gap-3">
      <div className="min-w-0">
        <h1 className="text-[19px] font-semibold tracking-[-0.01em] text-content">{title}</h1>
        {description ? (
          <p className="mt-1 max-w-[70ch] text-[13px] text-content-muted">{description}</p>
        ) : null}
      </div>
      {actions ? <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div> : null}
    </header>
  );
}
