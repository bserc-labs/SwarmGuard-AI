/**
 * Geofence vertex parsing.
 *
 * The rule under test: a malformed line fails the whole parse. Silently
 * skipping it would submit a different polygon than the operator entered.
 */

import { describe, expect, it } from "vitest";
import { parseVertices } from "./geofence";

describe("parseVertices", () => {
  it("parses lat, lng lines in order", () => {
    const { points, error } = parseVertices(
      "34.0530, -118.2450\n34.0530, -118.2400\n34.0490, -118.2400",
    );
    expect(error).toBeNull();
    expect(points).toEqual([
      [34.053, -118.245],
      [34.053, -118.24],
      [34.049, -118.24],
    ]);
  });

  it("accepts whitespace separation and blank lines", () => {
    const { points, error } = parseVertices("34.05 -118.24\n\n  34.06  -118.25 \n34.07 -118.26\n");
    expect(error).toBeNull();
    expect(points).toHaveLength(3);
  });

  it("treats empty input as nothing entered rather than an error", () => {
    expect(parseVertices("")).toEqual({ points: [], error: null });
    expect(parseVertices("   \n  ")).toEqual({ points: [], error: null });
  });

  it("requires at least three vertices", () => {
    const { error } = parseVertices("34.05, -118.24\n34.06, -118.25");
    expect(error).toContain("at least three");
  });

  it("fails the whole parse on a malformed line, naming it", () => {
    const { points, error } = parseVertices("34.05, -118.24\nnonsense\n34.07, -118.26");
    expect(points).toEqual([]);
    expect(error).toContain("Line 2");
  });

  it("rejects out-of-range latitude and longitude", () => {
    expect(parseVertices("91, 0\n1,1\n2,2").error).toContain("latitude");
    expect(parseVertices("0, 181\n1,1\n2,2").error).toContain("longitude");
  });

  it("rejects a line with the wrong number of values", () => {
    expect(parseVertices("34.05\n1,1\n2,2").error).toContain("Line 1");
    expect(parseVertices("34.05, -118.24, 99\n1,1\n2,2").error).toContain("Line 1");
  });

  it("accepts the coordinate extremes", () => {
    const { error } = parseVertices("90, 180\n-90, -180\n0, 0");
    expect(error).toBeNull();
  });
});
