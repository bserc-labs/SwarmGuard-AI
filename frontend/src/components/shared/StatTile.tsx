/**
 * Compact metric tile.
 *
 * `value` accepts null to mean "the backend did not report this", which renders
 * as an em dash. That distinction matters: a fleet with zero active drones and
 * a health endpoint that failed are different situations, and a tile that shows
 * "0" for both is lying about one of them.
 */

import type { ReactNode } from "react";
import { Icon, type IconName } from "@/components/ui/Icon";
import { ABSENT } from "@/lib/format";
import { cn } from "@/lib/utils";

export type StatTone = "neutral" | "accent" | "nominal" | "warning" | "critical";

const TONE_TEXT: Record<StatTone, string> = {
  neutral: "text-content",
  accent: "text-accent-bright",
  nominal: "text-nominal",
  warning: "text-warning",
  critical: "text-critical",
};

export function StatTile({
  label,
  value,
  unit,
  tone = "neutral",
  icon,
  detail,
  className,
}: {
  label: string;
  /** null renders as an em dash — "not reported", not zero. */
  value: string | number | null | undefined;
  unit?: string;
  tone?: StatTone;
  icon?: IconName;
  detail?: ReactNode;
  className?: string;
}) {
  const missing = value === null || value === undefined;
  const display = missing ? ABSENT : typeof value === "number" ? value.toLocaleString() : value;

  return (
    <div className={cn("rounded-panel border border-line bg-surface-raised p-3", className)}>
      <div className="flex items-center gap-1.5">
        {icon ? <Icon name={icon} size={13} className="shrink-0 text-content-dim" /> : null}
        <p className="truncate text-[11px] font-medium text-content-dim">{label}</p>
      </div>

      <p className="mt-1.5 flex items-baseline gap-1">
        <span
          className={cn(
            "text-[22px] font-semibold leading-none tabular",
            missing ? "text-content-dim" : TONE_TEXT[tone],
          )}
        >
          {display}
        </span>
        {unit && !missing ? (
          <span className="text-[12px] text-content-dim">{unit}</span>
        ) : null}
      </p>

      {detail ? (
        <p className="mt-1.5 text-[11px] leading-snug text-content-muted">{detail}</p>
      ) : missing ? (
        <p className="mt-1.5 text-[11px] leading-snug text-content-dim">Not reported</p>
      ) : null}
    </div>
  );
}
