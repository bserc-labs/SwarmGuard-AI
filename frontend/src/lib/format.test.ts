/**
 * Formatting rules.
 *
 * The important property throughout: absent input renders as an em dash, never
 * as a zero. Conflating "not reported" with "reported as zero" is the failure
 * mode this module exists to prevent.
 */

import { describe, expect, it } from "vitest";
import {
  ABSENT,
  attributionMagnitude,
  formatDuration,
  fractionAsPercent,
  humanizeEnum,
  latLon,
  num,
  parseTimestamp,
  relativeTime,
} from "./format";

describe("absent values", () => {
  it("renders an em dash rather than zero", () => {
    expect(num(null)).toBe(ABSENT);
    expect(num(undefined)).toBe(ABSENT);
    expect(num(NaN)).toBe(ABSENT);
    expect(latLon(null, 12)).toBe(ABSENT);
    expect(latLon(12, undefined)).toBe(ABSENT);
  });

  it("still renders a genuine zero", () => {
    expect(num(0)).toBe("0.0");
    expect(latLon(0, 0)).toBe("0.00000, 0.00000");
  });
});

describe("fractionAsPercent", () => {
  it("converts a 0-1 fraction", () => {
    expect(fractionAsPercent(0.482, 0)).toBe("48%");
    expect(fractionAsPercent(1)).toBe("100%");
  });

  it("withholds values outside the 0-1 range instead of guessing", () => {
    expect(fractionAsPercent(48)).toBe(ABSENT);
    expect(fractionAsPercent(-0.2)).toBe(ABSENT);
  });
});

describe("parseTimestamp", () => {
  it("treats an offset-free timestamp as UTC", () => {
    // The backend emits datetime.utcnow(), which has no offset. Without this,
    // every displayed time shifts by the viewer's timezone.
    const naive = parseTimestamp("2026-08-16T12:00:00");
    const explicit = parseTimestamp("2026-08-16T12:00:00Z");
    expect(naive?.getTime()).toBe(explicit?.getTime());
  });

  it("respects an offset when one is present", () => {
    const withOffset = parseTimestamp("2026-08-16T12:00:00+02:00");
    const utc = parseTimestamp("2026-08-16T10:00:00Z");
    expect(withOffset?.getTime()).toBe(utc?.getTime());
  });

  it("returns null for missing or unparseable input", () => {
    expect(parseTimestamp(null)).toBeNull();
    expect(parseTimestamp("")).toBeNull();
    expect(parseTimestamp("not a date")).toBeNull();
  });
});

describe("relativeTime", () => {
  const now = Date.parse("2026-08-16T12:00:00Z");

  it("describes recent and older instants", () => {
    expect(relativeTime("2026-08-16T11:59:50Z", now)).toBe("just now");
    expect(relativeTime("2026-08-16T11:55:00Z", now)).toBe("5m ago");
    expect(relativeTime("2026-08-16T09:00:00Z", now)).toBe("3h ago");
    expect(relativeTime("2026-08-14T12:00:00Z", now)).toBe("2d ago");
  });

  it("does not produce a negative interval for clock skew", () => {
    expect(relativeTime("2026-08-16T12:00:30Z", now)).toBe("just now");
  });
});

describe("formatDuration", () => {
  it("scales the unit to the magnitude", () => {
    expect(formatDuration(45)).toBe("45s");
    expect(formatDuration(90)).toBe("1m 30s");
    expect(formatDuration(7_200)).toBe("2h 0m");
  });

  it("rejects absent and negative input", () => {
    expect(formatDuration(null)).toBe(ABSENT);
    expect(formatDuration(-5)).toBe(ABSENT);
  });
});

describe("humanizeEnum", () => {
  it("converts backend enums to sentence case", () => {
    expect(humanizeEnum("RETURN_TO_HOME")).toBe("Return to home");
    expect(humanizeEnum("CRITICAL")).toBe("Critical");
  });

  it("keeps domain acronyms uppercase", () => {
    expect(humanizeEnum("GPS_SPOOFING")).toBe("GPS spoofing");
    expect(humanizeEnum("DOS")).toBe("DOS");
  });

  it("handles absent input", () => {
    expect(humanizeEnum(null)).toBe(ABSENT);
    expect(humanizeEnum("")).toBe(ABSENT);
  });
});

describe("attributionMagnitude", () => {
  it("reads whichever key the producer actually wrote", () => {
    // heartbeat_service and the socket's shap_top3 write `importance`; both
    // live detectors write `magnitude` and `shap_value` into the stored
    // incident. This previously read only `importance` and `value` — neither of
    // which a stored incident carries — so every incident detail page showed
    // "No attribution recorded".
    expect(attributionMagnitude({ importance: 0.48 })).toBe(0.48);
    expect(attributionMagnitude({ magnitude: 61.8 })).toBe(61.8);
    expect(attributionMagnitude({ shap_value: -0.22 })).toBe(-0.22);
    expect(attributionMagnitude({ value: 0.31 })).toBe(0.31);
  });

  it("reads the shape kinematic_guard actually stores", () => {
    // Verbatim from KinematicGuard.to_detection(): the exact dict written to
    // Incident.shap_values for a Tier 1 detection. If this entry reads as null,
    // the explainability panel is blank for every physics-detected incident.
    const violation = {
      feature: "gps_airframe_speed_mismatch",
      shap_value: 148.24,
      magnitude: 148.24,
      observed: 3706.1,
      threshold: 25.0,
      unit: "m/s",
    };
    expect(attributionMagnitude(violation)).toBe(148.24);
  });

  it("prefers the more specific key when several are present", () => {
    expect(attributionMagnitude({ importance: 0.5, magnitude: 0.2, value: 0.1 })).toBe(0.5);
    // magnitude is already absolute, so it wins over the signed shap_value.
    expect(attributionMagnitude({ magnitude: 0.9, shap_value: -0.9 })).toBe(0.9);
  });

  it("returns null when no key carries a number", () => {
    expect(attributionMagnitude({})).toBeNull();
    expect(attributionMagnitude({ feature: "speed" } as { importance?: number })).toBeNull();
  });

  it("preserves a genuine zero contribution", () => {
    expect(attributionMagnitude({ importance: 0 })).toBe(0);
    expect(attributionMagnitude({ magnitude: 0 })).toBe(0);
  });
});
