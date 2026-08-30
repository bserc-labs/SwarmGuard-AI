/**
 * Forensic incident export.
 *
 * Builds a report from data the backend actually returned. Two rules make the
 * output defensible as evidence:
 *
 *  1. Nothing is invented. Fields the payload omits are exported as null (JSON)
 *     or an empty cell (CSV), never as a default or placeholder.
 *  2. The report records its own provenance — who exported it, when, from which
 *     origin — and states plainly which sections were unavailable, so a reader
 *     can tell "no attribution was recorded" from "attribution was omitted here".
 */

import type { AuditLog, Incident, UserInfo } from "@/services/api";
import { attributionMagnitude, parseTimestamp } from "./format";

export interface ForensicReport {
  report: {
    generated_at: string;
    generated_by: string | null;
    organization_id: number | null;
    source: string;
    schema_version: string;
    notes: string[];
  };
  incident: Incident;
  attribution: {
    available: boolean;
    entries: Array<{ feature: string; magnitude: number; share_percent: number }>;
    note: string;
  };
  timeline: Array<{
    at: string;
    action: string;
    actor: string | null;
    previous_state: string | null;
    new_state: string | null;
    reason: string | null;
    ip_address: string | null;
  }>;
  audit_note: string;
}

const SCHEMA_VERSION = "swarmguard.forensic.v1";

/** Audit rows the backend links to this incident. */
export function relatedAuditLogs(incident: Incident, logs: AuditLog[]): AuditLog[] {
  const id = String(incident.id);
  return logs
    .filter(
      (log) =>
        (log.resource === "incident" && log.resource_id === id) ||
        log.target === id ||
        (log.resource_id === id && log.action.toUpperCase().includes("INCIDENT")),
    )
    .sort((a, b) => {
      const at = parseTimestamp(a.timestamp ?? a.created_at)?.getTime() ?? 0;
      const bt = parseTimestamp(b.timestamp ?? b.created_at)?.getTime() ?? 0;
      return at - bt;
    });
}

export function buildForensicReport({
  incident,
  auditLogs,
  user,
  auditAccessible,
  generatedAt,
}: {
  incident: Incident;
  auditLogs: AuditLog[];
  user: UserInfo | null;
  /** False when the caller's role cannot read the audit log. */
  auditAccessible: boolean;
  generatedAt: Date;
}): ForensicReport {
  const notes: string[] = [];

  const usable = (incident.shap_values ?? [])
    .map((entry) => {
      const magnitude = attributionMagnitude(entry);
      if (!entry.feature || magnitude === null || !Number.isFinite(magnitude)) return null;
      return { feature: entry.feature, magnitude: Math.abs(magnitude) };
    })
    .filter((e): e is { feature: string; magnitude: number } => e !== null);

  const total = usable.reduce((sum, e) => sum + e.magnitude, 0);
  const entries =
    total > 0
      ? usable
          .map((e) => ({
            feature: e.feature,
            magnitude: e.magnitude,
            share_percent: Number(((e.magnitude / total) * 100).toFixed(2)),
          }))
          .sort((a, b) => b.share_percent - a.share_percent)
      : [];

  if (entries.length === 0) {
    notes.push(
      "No per-feature attribution was stored on this incident; the attribution section is empty.",
    );
  }
  if (!incident.model_version) {
    notes.push("No model version was recorded on this incident.");
  }

  const related = auditAccessible ? relatedAuditLogs(incident, auditLogs) : [];
  const auditNote = !auditAccessible
    ? "The exporting user's role does not permit reading the audit log, so no timeline is included."
    : related.length === 0
      ? "No audit entries reference this incident."
      : `${related.length} audit ${related.length === 1 ? "entry" : "entries"} reference this incident.`;

  if (!auditAccessible) notes.push(auditNote);

  return {
    report: {
      generated_at: generatedAt.toISOString(),
      generated_by: user?.username ?? null,
      organization_id: incident.organization_id ?? user?.organization_id ?? null,
      source: typeof window === "undefined" ? "unknown" : window.location.origin,
      schema_version: SCHEMA_VERSION,
      notes,
    },
    incident,
    attribution: {
      available: entries.length > 0,
      entries,
      note:
        entries.length > 0
          ? "Shares are normalised across the values stored on this incident. The backend does not record which explainer produced them."
          : "No attribution values were stored.",
    },
    timeline: related.map((log) => ({
      at: log.timestamp ?? log.created_at,
      action: log.action,
      actor: log.actor ?? null,
      previous_state: log.previous_state ?? null,
      new_state: log.new_state ?? null,
      reason: log.reason ?? log.details ?? null,
      ip_address: log.ip_address ?? null,
    })),
    audit_note: auditNote,
  };
}

/* --------------------------------------------------------------------- CSV */

/** RFC 4180 escaping. null and undefined become an empty cell, never "null". */
function csvCell(value: unknown): string {
  if (value === null || value === undefined) return "";
  const text = typeof value === "object" ? JSON.stringify(value) : String(value);
  return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

function csvRow(cells: unknown[]): string {
  return cells.map(csvCell).join(",");
}

/**
 * Sectioned CSV. A single flat table cannot hold an incident, its attribution
 * and its timeline without either repeating the incident on every row or
 * dropping data, so the report is emitted as labelled blocks.
 */
export function forensicReportToCsv(report: ForensicReport): string {
  const lines: string[] = [];
  const i = report.incident;

  lines.push("# SwarmGuard forensic incident report");
  lines.push(csvRow(["schema_version", report.report.schema_version]));
  lines.push(csvRow(["generated_at", report.report.generated_at]));
  lines.push(csvRow(["generated_by", report.report.generated_by]));
  lines.push(csvRow(["organization_id", report.report.organization_id]));
  lines.push(csvRow(["source", report.report.source]));
  lines.push("");

  lines.push("# Incident");
  lines.push(csvRow(["field", "value"]));
  const fields: Array<[string, unknown]> = [
    ["id", i.id],
    ["drone_id", i.drone_id],
    ["organization_id", i.organization_id],
    ["mission_id", i.mission_id],
    ["attack_type", i.attack_type],
    ["severity", i.severity],
    ["status", i.status],
    ["priority", i.priority],
    ["threat_score", i.threat_score],
    ["anomaly_score", i.anomaly_score],
    ["threat_level", i.threat_level],
    ["assigned_analyst", i.assigned_analyst],
    ["model_version", i.model_version],
    ["feature_version", i.feature_version],
    ["detection_time", i.detection_time],
    ["resolution_time", i.resolution_time],
    ["created_at", i.created_at],
    ["updated_at", i.updated_at],
    ["recommended_action", i.recommended_action],
    ["explanation", i.explanation],
  ];
  for (const [key, value] of fields) lines.push(csvRow([key, value]));
  lines.push("");

  lines.push("# Feature attribution");
  if (report.attribution.entries.length === 0) {
    lines.push(csvRow(["note", report.attribution.note]));
  } else {
    lines.push(csvRow(["feature", "magnitude", "share_percent"]));
    for (const e of report.attribution.entries) {
      lines.push(csvRow([e.feature, e.magnitude, e.share_percent]));
    }
  }
  lines.push("");

  lines.push("# Timeline");
  if (report.timeline.length === 0) {
    lines.push(csvRow(["note", report.audit_note]));
  } else {
    lines.push(csvRow(["at", "action", "actor", "previous_state", "new_state", "reason", "ip_address"]));
    for (const e of report.timeline) {
      lines.push(
        csvRow([e.at, e.action, e.actor, e.previous_state, e.new_state, e.reason, e.ip_address]),
      );
    }
  }

  if (report.report.notes.length > 0) {
    lines.push("");
    lines.push("# Notes");
    for (const note of report.report.notes) lines.push(csvRow([note]));
  }

  return lines.join("\r\n");
}

export function forensicFilename(incident: Incident, format: "json" | "csv", at: Date): string {
  const stamp = at.toISOString().replace(/[:.]/g, "-").slice(0, 19);
  return `swarmguard-incident-${incident.id}-${stamp}.${format}`;
}

/** Triggers a browser download. Uses an object URL so large reports stream. */
export function downloadReport(filename: string, content: string, mime: string): void {
  const blob = new Blob([content], { type: `${mime};charset=utf-8` });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
  // Revoke on the next tick; revoking synchronously can cancel the download.
  setTimeout(() => URL.revokeObjectURL(url), 0);
}
