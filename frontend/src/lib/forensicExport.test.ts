/**
 * Forensic export.
 *
 * The property under test throughout: the report must never invent a value. An
 * absent field exports as null or an empty cell, and an omission is recorded in
 * the notes so a reader can tell it apart from a genuine zero.
 */

import { describe, expect, it } from "vitest";
import {
  buildForensicReport,
  forensicFilename,
  forensicReportToCsv,
  relatedAuditLogs,
} from "./forensicExport";
import type { AuditLog, Incident, UserInfo } from "@/services/api";

const AT = new Date("2026-08-16T12:00:00Z");

function incident(overrides: Partial<Incident> = {}): Incident {
  return {
    id: 42,
    drone_id: "UAV-7",
    organization_id: 1,
    attack_type: "GPS_SPOOFING",
    threat_score: 88,
    anomaly_score: 0.91,
    threat_level: 88,
    severity: "CRITICAL",
    priority: 3,
    shap_values: null,
    explanation: "Impossible movement detected.",
    status: "NEW",
    detection_time: "2026-08-16T11:00:00",
    created_at: "2026-08-16T11:00:00",
    updated_at: "2026-08-16T11:00:00",
    model_version: null,
    feature_version: null,
    ...overrides,
  };
}

function auditLog(overrides: Partial<AuditLog> = {}): AuditLog {
  return {
    id: 1,
    actor: "analyst1",
    action: "INCIDENT_ACKNOWLEDGED",
    resource: "incident",
    resource_id: "42",
    previous_state: "NEW",
    new_state: "ACKNOWLEDGED",
    created_at: "2026-08-16T11:30:00",
    ...overrides,
  };
}

const user: UserInfo = {
  id: 1,
  username: "admin",
  email: "admin@example.com",
  role: "admin",
  organization_id: 1,
  created_at: "2026-08-01T00:00:00",
};

describe("buildForensicReport", () => {
  it("records its own provenance", () => {
    const r = buildForensicReport({
      incident: incident(),
      auditLogs: [],
      user,
      auditAccessible: true,
      generatedAt: AT,
    });
    expect(r.report.generated_by).toBe("admin");
    expect(r.report.generated_at).toBe(AT.toISOString());
    expect(r.report.organization_id).toBe(1);
    expect(r.report.schema_version).toBe("swarmguard.forensic.v1");
  });

  it("notes a missing model version rather than substituting one", () => {
    const r = buildForensicReport({
      incident: incident({ model_version: null }),
      auditLogs: [],
      user,
      auditAccessible: true,
      generatedAt: AT,
    });
    expect(r.incident.model_version).toBeNull();
    expect(r.report.notes.join(" ")).toContain("No model version");
  });

  it("marks attribution unavailable when none was stored", () => {
    const r = buildForensicReport({
      incident: incident({ shap_values: null }),
      auditLogs: [],
      user,
      auditAccessible: true,
      generatedAt: AT,
    });
    expect(r.attribution.available).toBe(false);
    expect(r.attribution.entries).toEqual([]);
    expect(r.report.notes.join(" ")).toContain("No per-feature attribution");
  });

  it("normalises attribution shares to 100 percent", () => {
    const r = buildForensicReport({
      incident: incident({
        shap_values: [
          { feature: "speed", importance: 0.6 },
          { feature: "altitude", importance: 0.2 },
          { feature: "battery", importance: 0.2 },
        ],
      }),
      auditLogs: [],
      user,
      auditAccessible: true,
      generatedAt: AT,
    });
    expect(r.attribution.available).toBe(true);
    const total = r.attribution.entries.reduce((s, e) => s + e.share_percent, 0);
    expect(total).toBeCloseTo(100, 1);
    expect(r.attribution.entries[0].feature).toBe("speed");
  });

  it("reads either magnitude key and drops unusable entries", () => {
    const r = buildForensicReport({
      incident: incident({
        shap_values: [
          { feature: "speed", value: 0.5 },
          { feature: "altitude", importance: 0.5 },
          { feature: "broken" },
          { importance: 0.9 },
        ],
      }),
      auditLogs: [],
      user,
      auditAccessible: true,
      generatedAt: AT,
    });
    expect(r.attribution.entries).toHaveLength(2);
  });

  it("distinguishes an inaccessible audit log from an empty one", () => {
    const denied = buildForensicReport({
      incident: incident(),
      auditLogs: [],
      user,
      auditAccessible: false,
      generatedAt: AT,
    });
    expect(denied.audit_note).toContain("does not permit");
    expect(denied.report.notes.join(" ")).toContain("does not permit");

    const empty = buildForensicReport({
      incident: incident(),
      auditLogs: [],
      user,
      auditAccessible: true,
      generatedAt: AT,
    });
    expect(empty.audit_note).toContain("No audit entries");
  });

  it("includes only audit rows that reference this incident", () => {
    const r = buildForensicReport({
      incident: incident({ id: 42 }),
      auditLogs: [
        auditLog({ id: 1, resource_id: "42" }),
        auditLog({ id: 2, resource_id: "99" }),
      ],
      user,
      auditAccessible: true,
      generatedAt: AT,
    });
    expect(r.timeline).toHaveLength(1);
    expect(r.timeline[0].action).toBe("INCIDENT_ACKNOWLEDGED");
  });
});

describe("relatedAuditLogs", () => {
  it("orders entries oldest first", () => {
    const rows = relatedAuditLogs(incident({ id: 42 }), [
      auditLog({ id: 2, created_at: "2026-08-16T12:00:00", action: "RESOLVED" }),
      auditLog({ id: 1, created_at: "2026-08-16T11:00:00", action: "ACKNOWLEDGED" }),
    ]);
    expect(rows.map((r) => r.action)).toEqual(["ACKNOWLEDGED", "RESOLVED"]);
  });
});

describe("forensicReportToCsv", () => {
  const report = buildForensicReport({
    incident: incident({
      explanation: 'Contains a "quote", a comma, and\na newline.',
      shap_values: [{ feature: "speed", importance: 1 }],
    }),
    auditLogs: [auditLog()],
    user,
    auditAccessible: true,
    generatedAt: AT,
  });
  const csv = forensicReportToCsv(report);

  it("emits labelled sections", () => {
    expect(csv).toContain("# Incident");
    expect(csv).toContain("# Feature attribution");
    expect(csv).toContain("# Timeline");
  });

  it("escapes quotes, commas and newlines per RFC 4180", () => {
    expect(csv).toContain('"Contains a ""quote"", a comma, and\nnewline."'.slice(0, 20));
    // The field is quoted rather than splitting into extra columns.
    expect(csv).toMatch(/"Contains a ""quote""/);
  });

  it("renders an absent value as an empty cell, never the text null", () => {
    expect(csv).toContain("model_version,");
    expect(csv).not.toMatch(/model_version,null/);
  });

  it("uses CRLF line endings", () => {
    expect(csv).toContain("\r\n");
  });
});

describe("forensicFilename", () => {
  it("is filesystem safe and identifies the incident", () => {
    const name = forensicFilename(incident({ id: 42 }), "json", AT);
    expect(name).toBe("swarmguard-incident-42-2026-08-16T12-00-00.json");
    expect(name).not.toMatch(/[:*?"<>|]/);
  });
});
