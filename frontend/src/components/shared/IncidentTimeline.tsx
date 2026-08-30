/**
 * Incident lifecycle timeline, built from audit-log rows.
 *
 * The timeline shows only events the audit trail actually recorded. The
 * previous version rendered a fixed NEW -> ACKNOWLEDGED -> RESOLVED -> CLOSED
 * ladder with placeholder timestamps for stages that had not happened, which
 * read as a completed history that did not exist.
 */

import { useMemo } from "react";
import type { AuditLog, Incident } from "@/services/api";
import { EmptyState } from "@/components/ui/DataState";
import { Mono } from "@/components/ui/primitives";
import { formatDateTime, humanizeEnum, relativeTime } from "@/lib/format";
import { cn } from "@/lib/utils";

interface TimelineEvent {
  key: string;
  title: string;
  actor: string | null;
  at: string;
  detail: string | null;
  transition: string | null;
  tone: "critical" | "accent" | "neutral";
}

function toneForAction(action: string): TimelineEvent["tone"] {
  const a = action.toUpperCase();
  if (a.includes("CREATE") || a.includes("DETECT")) return "critical";
  if (a.includes("RESOLVE") || a.includes("CLOSE")) return "neutral";
  return "accent";
}

export function IncidentTimeline({
  incident,
  auditLogs,
}: {
  incident: Incident;
  auditLogs: AuditLog[];
}) {
  const events = useMemo<TimelineEvent[]>(() => {
    const detection: TimelineEvent = {
      key: "detection",
      title: "Incident recorded",
      actor: null,
      at: incident.detection_time ?? incident.created_at,
      detail: `Stored with severity ${humanizeEnum(incident.severity).toLowerCase()}.`,
      transition: null,
      tone: "critical",
    };

    // Rows the backend links to this incident, by resource id or target.
    const related = auditLogs
      .filter((log) => {
        const id = String(incident.id);
        return (
          (log.resource === "incident" && log.resource_id === id) ||
          log.target === id ||
          (log.resource_id === id && log.action.toUpperCase().includes("INCIDENT"))
        );
      })
      .map<TimelineEvent>((log) => ({
        key: `log-${log.id}`,
        title: humanizeEnum(log.action),
        actor: log.actor,
        at: log.timestamp ?? log.created_at,
        detail: log.reason ?? log.details ?? null,
        transition:
          log.previous_state && log.new_state
            ? `${humanizeEnum(log.previous_state)} → ${humanizeEnum(log.new_state)}`
            : (log.new_state ?? null),
        tone: toneForAction(log.action),
      }));

    return [detection, ...related].sort(
      (a, b) => new Date(a.at).getTime() - new Date(b.at).getTime(),
    );
  }, [incident, auditLogs]);

  if (events.length === 0) {
    return <EmptyState compact title="No recorded activity" />;
  }

  return (
    <ol className="flex flex-col">
      {events.map((event, index) => {
        const last = index === events.length - 1;
        return (
          <li key={event.key} className="relative flex gap-3 pb-4 last:pb-0">
            {/* Rail */}
            <div className="flex shrink-0 flex-col items-center">
              <span
                aria-hidden="true"
                className={cn(
                  "mt-1 h-2 w-2 shrink-0 rounded-full ring-2 ring-surface-raised",
                  event.tone === "critical"
                    ? "bg-critical"
                    : event.tone === "accent"
                      ? "bg-accent"
                      : "bg-content-dim",
                )}
              />
              {!last ? <span aria-hidden="true" className="mt-1 w-px flex-1 bg-line" /> : null}
            </div>

            <div className="min-w-0 flex-1 pb-0.5">
              <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
                <p className="text-[13px] font-medium text-content">{event.title}</p>
                <span className="text-[11px] text-content-dim" title={formatDateTime(event.at)}>
                  {relativeTime(event.at)}
                </span>
              </div>

              {event.transition ? (
                <p className="mt-0.5 text-[12px] text-content-muted">{event.transition}</p>
              ) : null}

              {event.detail ? (
                <p className="mt-0.5 text-[12px] leading-snug text-content-muted">{event.detail}</p>
              ) : null}

              {event.actor ? (
                <p className="mt-0.5 text-[11px] text-content-dim">
                  by <Mono className="text-content-muted">{event.actor}</Mono>
                </p>
              ) : null}
            </div>
          </li>
        );
      })}
    </ol>
  );
}
