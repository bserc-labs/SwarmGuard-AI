/**
 * Display formatting.
 *
 * Every function here returns an em dash for absent input rather than "0",
 * "N/A", or an empty string. A missing value and a zero value mean different
 * things in telemetry, and the console must not conflate them.
 */

export const ABSENT = "—";

function isPresent(value: unknown): boolean {
  return value !== null && value !== undefined && !(typeof value === "number" && Number.isNaN(value));
}

/* --------------------------------------------------------------- numbers */

export function num(value: number | null | undefined, digits = 1): string {
  if (!isPresent(value)) return ABSENT;
  return (value as number).toFixed(digits);
}

export function int(value: number | null | undefined): string {
  if (!isPresent(value)) return ABSENT;
  return Math.round(value as number).toLocaleString();
}

export function percent(value: number | null | undefined, digits = 0): string {
  if (!isPresent(value)) return ABSENT;
  return `${(value as number).toFixed(digits)}%`;
}

/** Formats a 0–1 fraction as a percentage. Returns ABSENT outside that range. */
export function fractionAsPercent(value: number | null | undefined, digits = 0): string {
  if (!isPresent(value)) return ABSENT;
  const v = value as number;
  if (v < 0 || v > 1) return ABSENT;
  return `${(v * 100).toFixed(digits)}%`;
}

/* ------------------------------------------------------------ coordinates */

export function coord(value: number | null | undefined): string {
  if (!isPresent(value)) return ABSENT;
  return (value as number).toFixed(5);
}

export function latLon(
  lat: number | null | undefined,
  lon: number | null | undefined,
): string {
  if (!isPresent(lat) || !isPresent(lon)) return ABSENT;
  return `${coord(lat)}, ${coord(lon)}`;
}

/* ------------------------------------------------------------------ time */

/**
 * The backend emits UTC timestamps with an offset (every column is
 * timestamptz). Older records and any caller still sending a bare timestamp
 * lack one, and Date parsing would treat those as local time and shift them by
 * the viewer's offset, so append Z when absent.
 */
export function parseTimestamp(value: string | null | undefined): Date | null {
  if (!value) return null;
  const hasZone = /[Zz]$|[+-]\d{2}:?\d{2}$/.test(value);
  const date = new Date(hasZone ? value : `${value}Z`);
  return Number.isNaN(date.getTime()) ? null : date;
}

export function formatTime(value: string | null | undefined): string {
  const date = parseTimestamp(value);
  if (!date) return ABSENT;
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

export function formatDateTime(value: string | null | undefined): string {
  const date = parseTimestamp(value);
  if (!date) return ABSENT;
  return date.toLocaleString([], {
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function formatUtcClock(date: Date): string {
  return `${date.toISOString().slice(11, 19)} UTC`;
}

/** "just now", "4m ago", "3h ago", "2d ago". */
export function relativeTime(value: string | null | undefined, now: number = Date.now()): string {
  const date = parseTimestamp(value);
  if (!date) return ABSENT;

  const seconds = Math.round((now - date.getTime()) / 1000);
  if (seconds < 0) return "just now";
  if (seconds < 45) return "just now";
  if (seconds < 3600) return `${Math.round(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)}h ago`;
  return `${Math.round(seconds / 86400)}d ago`;
}

export function formatDuration(seconds: number | null | undefined): string {
  if (!isPresent(seconds) || (seconds as number) < 0) return ABSENT;
  const s = Math.round(seconds as number);
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m ${s % 60}s`;
  const hours = Math.floor(s / 3600);
  const minutes = Math.floor((s % 3600) / 60);
  return `${hours}h ${minutes}m`;
}

/* ----------------------------------------------------------------- labels */

/**
 * Turns a backend enum into sentence case for display.
 * "GPS_SPOOFING" -> "GPS spoofing", "RETURN_TO_HOME" -> "Return to home".
 *
 * Acronyms stay uppercase. The console avoids all-caps body text, but these
 * are proper nouns in the domain.
 */
const ACRONYMS = new Set(["GPS", "DOS", "RF", "AI", "ID", "UAV", "MAV", "SHAP"]);

export function humanizeEnum(value: string | null | undefined): string {
  if (!value) return ABSENT;
  const words = value.split(/[_\s]+/).filter(Boolean);
  if (words.length === 0) return ABSENT;

  return words
    .map((word, index) => {
      const upper = word.toUpperCase();
      if (ACRONYMS.has(upper)) return upper;
      const lower = word.toLowerCase();
      return index === 0 ? lower.charAt(0).toUpperCase() + lower.slice(1) : lower;
    })
    .join(" ");
}

/**
 * Reads whichever magnitude key a feature-attribution entry actually carries.
 *
 * Four keys are in play because three producers disagree, and reading only two
 * of them meant every stored incident rendered "No attribution recorded":
 *
 *  - `importance`  heartbeat_service, and the `shap_top3` payload the socket
 *                  sends to the alert banner.
 *  - `magnitude`   kinematic_guard (violation exceedance factor) and
 *                  explainability.py (absolute SHAP contribution). This is the
 *                  key both live detectors write into `Incident.shap_values`,
 *                  and it was the one not being read.
 *  - `shap_value`  same two producers, signed rather than absolute. Kept as a
 *                  fallback for rows written before `magnitude` existed.
 *  - `value`       no current producer; retained so an older record still reads.
 *
 * Order is by specificity, not preference: `magnitude` is already absolute, so
 * it is consulted before the signed `shap_value` to avoid a needless abs().
 */
export function attributionMagnitude(entry: {
  importance?: number;
  magnitude?: number;
  shap_value?: number;
  value?: number;
}): number | null {
  if (isPresent(entry.importance)) return entry.importance as number;
  if (isPresent(entry.magnitude)) return entry.magnitude as number;
  if (isPresent(entry.shap_value)) return entry.shap_value as number;
  if (isPresent(entry.value)) return entry.value as number;
  return null;
}
