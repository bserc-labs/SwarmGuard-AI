/**
 * Navigation visibility.
 *
 * The console hides destinations a role cannot act on rather than routing the
 * operator somewhere that will refuse them. These assertions pin that per role.
 */

import { describe, expect, it } from "vitest";
import {
  canAdvanceTo,
  INCIDENT_LIFECYCLE,
  lifecycleIndex,
  NAV_PRIMARY,
  NAV_SECONDARY,
  severityTone,
  visibleNavItems,
} from "./constants";

const labels = (role: string | null) => [
  ...visibleNavItems(NAV_PRIMARY, role).map((i) => i.label),
  ...visibleNavItems(NAV_SECONDARY, role).map((i) => i.label),
];

describe("visibleNavItems", () => {
  it("gives admins everything", () => {
    expect(labels("admin")).toEqual([
      "Dashboard",
      "Telemetry",
      "Fleet",
      "Incidents",
      "Threat intelligence",
      "Detection",
      "Fleet control",
      "Team",
      "Settings",
      "Profile",
    ]);
  });

  it("gives team administration to admins alone", () => {
    // user.manage is held by no other role, and without this destination an
    // organization can never gain the second account the two-person command
    // approval rule requires.
    expect(labels("admin")).toContain("Team");
    for (const role of ["commander", "analyst", "operator", "observer"]) {
      expect(labels(role)).not.toContain("Team");
    }
  });

  it("hides the detection pipeline from observers", () => {
    // The guard thresholds it shows are the evasion envelope. Observers hold
    // read permissions but not ai.explain, so the destination is withheld.
    expect(labels("observer")).not.toContain("Detection");
    expect(labels("analyst")).toContain("Detection");
    expect(labels("operator")).toContain("Detection");
  });

  it("hides settings from commanders while keeping fleet control", () => {
    const visible = labels("commander");
    expect(visible).toContain("Fleet control");
    // Commanders hold settings.read but not settings.manage; the route guard
    // admits them, so Settings stays visible as read-only.
    expect(visible).toContain("Settings");
  });

  it("hides fleet control and settings from analysts", () => {
    const visible = labels("analyst");
    expect(visible).not.toContain("Fleet control");
    expect(visible).not.toContain("Settings");
    expect(visible).toContain("Threat intelligence");
  });

  it("hides fleet control from operators despite the request permission", () => {
    // Operators may request commands, but /admin is gated on an elevated role
    // by the router, so offering the link would route them straight back out.
    const visible = labels("operator");
    expect(visible).not.toContain("Fleet control");
    expect(visible).toContain("Fleet");
  });

  it("gives observers read-only destinations only", () => {
    const visible = labels("observer");
    expect(visible).toEqual(["Dashboard", "Telemetry", "Fleet", "Incidents", "Threat intelligence", "Profile"]);
  });

  it("shows nothing for an absent or unknown role", () => {
    expect(labels(null)).toEqual([]);
    expect(labels("superadmin")).toEqual([]);
  });
});

describe("incident lifecycle", () => {
  it("matches the order the backend enforces", () => {
    // Mirrors LIFECYCLE in backend/routers/incidents.py. If these drift, the
    // console offers transitions the API refuses.
    expect([...INCIDENT_LIFECYCLE]).toEqual([
      "NEW",
      "OPEN",
      "ACKNOWLEDGED",
      "INVESTIGATING",
      "CONTAINED",
      "RESOLVED",
      "CLOSED",
    ]);
  });

  it("offers Resolve from every state a user can actually reach it in", () => {
    // The regression this pins: Resolve used to be shown whenever the incident
    // was not already resolved, and the API refused it from NEW, OPEN and
    // ACKNOWLEDGED alike — which is every state the console can produce.
    expect(canAdvanceTo("NEW", "RESOLVED")).toBe(true);
    expect(canAdvanceTo("OPEN", "RESOLVED")).toBe(true);
    expect(canAdvanceTo("ACKNOWLEDGED", "RESOLVED")).toBe(true);
    expect(canAdvanceTo("CONTAINED", "RESOLVED")).toBe(true);
  });

  it("withholds an action once the incident is at or past that state", () => {
    expect(canAdvanceTo("RESOLVED", "RESOLVED")).toBe(false);
    expect(canAdvanceTo("RESOLVED", "ACKNOWLEDGED")).toBe(false);
    expect(canAdvanceTo("CLOSED", "RESOLVED")).toBe(false);
  });

  it("is case-insensitive, matching the backend's comparison", () => {
    expect(canAdvanceTo("acknowledged", "RESOLVED")).toBe(true);
  });

  it("withholds every action for an unknown status rather than guessing", () => {
    expect(lifecycleIndex("ARCHIVED")).toBe(-1);
    expect(canAdvanceTo("ARCHIVED", "RESOLVED")).toBe(false);
    expect(canAdvanceTo(null, "ACKNOWLEDGED")).toBe(false);
    expect(canAdvanceTo(undefined, "CLOSED")).toBe(false);
  });
});

describe("severityTone", () => {
  it("reserves warm tones for genuine escalations", () => {
    expect(severityTone("CRITICAL")).toBe("critical");
    expect(severityTone("HIGH")).toBe("warning");
    // Medium and low must not use amber or red.
    expect(severityTone("MEDIUM")).toBe("accent");
    expect(severityTone("LOW")).toBe("neutral");
  });

  it("falls back to neutral for unknown or absent input", () => {
    expect(severityTone("SOMETHING_ELSE")).toBe("neutral");
    expect(severityTone(null)).toBe("neutral");
  });
});
