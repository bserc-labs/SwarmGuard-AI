/**
 * RBAC mirror.
 *
 * These assertions encode the backend's ROLE_PERMISSIONS table. If a test here
 * fails after a backend change, the mirror is stale and the console will offer
 * controls that 403 (or hide ones that would work).
 */

import { describe, expect, it } from "vitest";
import { hasPermission, isElevated, permissionsFor, Permissions, ROLE_PERMISSIONS } from "./rbac";

describe("hasPermission", () => {
  it("matches roles case-insensitively, as the backend does", () => {
    expect(hasPermission("ADMIN", Permissions.USER_MANAGE)).toBe(true);
    expect(hasPermission("admin", Permissions.USER_MANAGE)).toBe(true);
    expect(hasPermission("Admin", Permissions.USER_MANAGE)).toBe(true);
  });

  it("denies everything for an absent or unknown role", () => {
    expect(hasPermission(null, Permissions.TELEMETRY_READ)).toBe(false);
    expect(hasPermission(undefined, Permissions.TELEMETRY_READ)).toBe(false);
    expect(hasPermission("superadmin", Permissions.TELEMETRY_READ)).toBe(false);
  });
});

describe("role boundaries", () => {
  it("gives observers read access but no actions", () => {
    expect(hasPermission("observer", Permissions.INCIDENT_READ)).toBe(true);
    expect(hasPermission("observer", Permissions.INCIDENT_ACKNOWLEDGE)).toBe(false);
    expect(hasPermission("observer", Permissions.DRONE_COMMAND_REQUEST)).toBe(false);
    expect(hasPermission("observer", Permissions.AI_EXPLAIN)).toBe(false);
  });

  it("lets operators request commands but never approve them", () => {
    // The two-person rule depends on this split.
    expect(hasPermission("operator", Permissions.DRONE_COMMAND_REQUEST)).toBe(true);
    expect(hasPermission("operator", Permissions.DRONE_COMMAND_APPROVE)).toBe(false);
  });

  it("lets analysts resolve incidents but not close them", () => {
    expect(hasPermission("analyst", Permissions.INCIDENT_RESOLVE)).toBe(true);
    expect(hasPermission("analyst", Permissions.INCIDENT_CLOSE)).toBe(false);
  });

  it("reserves user and organization management for admins", () => {
    expect(hasPermission("admin", Permissions.USER_MANAGE)).toBe(true);
    expect(hasPermission("commander", Permissions.USER_MANAGE)).toBe(false);
    expect(hasPermission("analyst", Permissions.USER_MANAGE)).toBe(false);
  });

  it("reserves settings changes for admins", () => {
    expect(hasPermission("admin", Permissions.SETTINGS_MANAGE)).toBe(true);
    expect(hasPermission("commander", Permissions.SETTINGS_MANAGE)).toBe(false);
    expect(hasPermission("commander", Permissions.SETTINGS_READ)).toBe(true);
  });
});

describe("permissionsFor", () => {
  it("returns the full set for a known role", () => {
    expect(permissionsFor("admin")).toHaveLength(ROLE_PERMISSIONS.admin.size);
  });

  it("returns nothing for an unknown role", () => {
    expect(permissionsFor("nobody")).toEqual([]);
  });
});

describe("isElevated", () => {
  it("matches the router role guard on /admin and /settings", () => {
    expect(isElevated("admin")).toBe(true);
    expect(isElevated("commander")).toBe(true);
    expect(isElevated("analyst")).toBe(false);
    expect(isElevated("operator")).toBe(false);
    expect(isElevated(null)).toBe(false);
  });
});
