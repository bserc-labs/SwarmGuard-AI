import { describe, expect, it } from "vitest";
import { hasPlottablePosition, mergePositions } from "./telemetry";
import type { TelemetryPacket, TelemetryRecord } from "@/services/api";

function record(overrides: Partial<TelemetryRecord> = {}): TelemetryRecord {
  return {
    drone_id: "UAV-1",
    latitude: 34.05,
    longitude: -118.24,
    altitude: 100,
    speed: 12,
    battery: 80,
    packet_sequence: 1,
    created_at: "2026-08-16T12:00:00",
    ...overrides,
  };
}

function packet(overrides: Partial<TelemetryPacket> = {}): TelemetryPacket {
  return {
    drone_id: "UAV-1",
    latitude: 40,
    longitude: -74,
    altitude: 200,
    speed: 20,
    battery: 60,
    packet_sequence: 99,
    ...overrides,
  };
}

describe("mergePositions", () => {
  it("returns stored rows when no live frames have arrived", () => {
    const merged = mergePositions([record()], {});
    expect(merged).toHaveLength(1);
    expect(merged[0].latitude).toBe(34.05);
  });

  it("lets a live frame win over the polled row for the same drone", () => {
    // The socket is newer than anything the last poll returned, so a stale
    // stored row must never overwrite a live position.
    const merged = mergePositions([record()], { "UAV-1": packet() });
    expect(merged).toHaveLength(1);
    expect(merged[0].latitude).toBe(40);
    expect(merged[0].battery).toBe(60);
  });

  it("keeps drones that appear in only one source", () => {
    const merged = mergePositions([record({ drone_id: "UAV-1" })], {
      "UAV-2": packet({ drone_id: "UAV-2" }),
    });
    expect(merged.map((d) => d.drone_id).sort()).toEqual(["UAV-1", "UAV-2"]);
  });

  it("returns nothing when both sources are empty", () => {
    expect(mergePositions([], {})).toEqual([]);
  });
});

describe("hasPlottablePosition", () => {
  it("accepts coordinates inside the valid range", () => {
    expect(hasPlottablePosition({ drone_id: "a", latitude: 0, longitude: 0 })).toBe(true);
    expect(hasPlottablePosition({ drone_id: "a", latitude: -90, longitude: 180 })).toBe(true);
  });

  it("rejects out-of-range and non-finite coordinates", () => {
    expect(hasPlottablePosition({ drone_id: "a", latitude: 91, longitude: 0 })).toBe(false);
    expect(hasPlottablePosition({ drone_id: "a", latitude: 0, longitude: 181 })).toBe(false);
    expect(hasPlottablePosition({ drone_id: "a", latitude: NaN, longitude: 0 })).toBe(false);
  });
});
