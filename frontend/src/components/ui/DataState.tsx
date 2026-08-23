/**
 * Honest state rendering.
 *
 * Every panel that reads from the backend routes through <DataState>, so the
 * five outcomes a request can have are handled uniformly and none of them
 * silently render as an empty box or a zero.
 *
 *   loading            request in flight
 *   error (403)        the role lacks the permission this route requires
 *   error (404)        the backend has no such route or record
 *   error (network)    the server could not be reached
 *   empty              request succeeded, no rows
 *
 * A sixth, <Unavailable>, is used where the UI once displayed data that the
 * backend cannot supply. It states that plainly rather than showing a
 * placeholder or an invented value.
 */

import type { ReactNode } from "react";
import { ApiError } from "@/services/api";
import { Icon, type IconName } from "./Icon";
import { Skeleton } from "./primitives";

/* ------------------------------------------------------------- status box */

function StatusBox({
  icon,
  title,
  detail,
  tone = "neutral",
  action,
  compact = false,
}: {
  icon: IconName;
  title: string;
  detail?: ReactNode;
  tone?: "neutral" | "warning" | "critical";
  action?: ReactNode;
  compact?: boolean;
}) {
  const toneClass =
    tone === "critical"
      ? "text-critical"
      : tone === "warning"
        ? "text-warning"
        : "text-content-dim";

  return (
    <div
      className={`flex flex-col items-center justify-center gap-2 text-center ${
        compact ? "px-4 py-6" : "px-6 py-12"
      }`}
    >
      <Icon name={icon} size={compact ? 18 : 22} className={toneClass} />
      <p className="text-[13px] font-medium text-content">{title}</p>
      {detail ? (
        <p className="max-w-[46ch] text-[12px] leading-relaxed text-content-muted">{detail}</p>
      ) : null}
      {action ? <div className="mt-1">{action}</div> : null}
    </div>
  );
}

/* --------------------------------------------------------------- variants */

export function LoadingState({ rows = 3, compact = false }: { rows?: number; compact?: boolean }) {
  return (
    <div
      className={compact ? "flex flex-col gap-2 p-3" : "flex flex-col gap-2.5 p-4"}
      role="status"
      aria-live="polite"
      aria-label="Loading"
    >
      {Array.from({ length: rows }, (_, i) => (
        <Skeleton key={i} className={i === rows - 1 ? "w-2/3" : "w-full"} />
      ))}
    </div>
  );
}

export function EmptyState({
  title = "No records",
  detail,
  icon = "info",
  action,
  compact = false,
}: {
  title?: string;
  detail?: ReactNode;
  icon?: IconName;
  action?: ReactNode;
  compact?: boolean;
}) {
  return <StatusBox icon={icon} title={title} detail={detail} action={action} compact={compact} />;
}

export function PermissionDeniedState({ detail, compact = false }: { detail?: string; compact?: boolean }) {
  return (
    <StatusBox
      icon="lock"
      title="You do not have access to this"
      detail={
        detail ??
        "Your role does not include the permission this view requires. An administrator can grant it."
      }
      compact={compact}
    />
  );
}

export function ErrorState({
  error,
  onRetry,
  compact = false,
}: {
  error: unknown;
  onRetry?: () => void;
  compact?: boolean;
}) {
  const apiError = error instanceof ApiError ? error : null;

  if (apiError?.isForbidden) return <PermissionDeniedState compact={compact} />;

  if (apiError?.isNetwork) {
    return (
      <StatusBox
        icon="signal"
        title="Cannot reach the server"
        detail="The request did not complete. Check that the backend is running and reachable."
        tone="warning"
        compact={compact}
        action={
          onRetry ? (
            <button
              type="button"
              onClick={onRetry}
              className="rounded-[5px] border border-line-strong bg-surface-overlay px-3 py-1.5 text-[12px] text-content hover:bg-surface-hover"
            >
              Try again
            </button>
          ) : undefined
        }
      />
    );
  }

  if (apiError?.isNotFound) {
    return (
      <StatusBox
        icon="info"
        title="Not found"
        detail="This record does not exist, or the endpoint is not available on this backend."
        compact={compact}
      />
    );
  }

  const message = error instanceof Error ? error.message : "The request failed.";
  return (
    <StatusBox
      icon="alert"
      title="Request failed"
      detail={message}
      tone="critical"
      compact={compact}
      action={
        onRetry ? (
          <button
            type="button"
            onClick={onRetry}
            className="rounded-[5px] border border-line-strong bg-surface-overlay px-3 py-1.5 text-[12px] text-content hover:bg-surface-hover"
          >
            Try again
          </button>
        ) : undefined
      }
    />
  );
}

/**
 * For capability the backend does not expose. Used instead of fabricating a
 * value, a placeholder score, or a decorative chart with no data behind it.
 */
export function UnavailableState({
  title = "Not available",
  detail,
  compact = false,
}: {
  title?: string;
  detail: ReactNode;
  compact?: boolean;
}) {
  return <StatusBox icon="info" title={title} detail={detail} compact={compact} />;
}

/* ------------------------------------------------------------- controller */

export interface DataStateProps<T> {
  isLoading: boolean;
  isError: boolean;
  error?: unknown;
  data: T | undefined;
  onRetry?: () => void;
  /** Treated as empty when true. Defaults to detecting an empty array. */
  isEmpty?: (data: T) => boolean;
  loadingRows?: number;
  compact?: boolean;
  empty?: ReactNode;
  children: (data: T) => ReactNode;
}

export function DataState<T>({
  isLoading,
  isError,
  error,
  data,
  onRetry,
  isEmpty,
  loadingRows = 3,
  compact = false,
  empty,
  children,
}: DataStateProps<T>) {
  if (isLoading) return <LoadingState rows={loadingRows} compact={compact} />;
  if (isError) return <ErrorState error={error} onRetry={onRetry} compact={compact} />;
  if (data === undefined) return <EmptyState compact={compact} />;

  const resolvedEmpty = isEmpty
    ? isEmpty(data)
    : Array.isArray(data) && data.length === 0;

  if (resolvedEmpty) return <>{empty ?? <EmptyState compact={compact} />}</>;

  return <>{children(data)}</>;
}
