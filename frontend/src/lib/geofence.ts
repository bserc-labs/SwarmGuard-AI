/**
 * Geofence geometry helpers.
 *
 * Kept out of the component modules so they can be unit tested without
 * rendering, and so those files stay fast-refresh clean.
 */

export interface ParsedVertices {
  points: [number, number][];
  error: string | null;
}

/**
 * Parses "lat, lng" lines into coordinate pairs, matching the [lat, lng]
 * ordering the backend stores and the map reads.
 *
 * A malformed or out-of-range line fails the whole parse. Skipping bad lines
 * would silently submit a different polygon than the operator entered, and a
 * geofence with a quietly-missing vertex is a wrong geofence, not a slightly
 * imprecise one.
 */
export function parseVertices(input: string): ParsedVertices {
  const lines = input
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);

  if (lines.length === 0) return { points: [], error: null };

  const points: [number, number][] = [];

  for (let index = 0; index < lines.length; index += 1) {
    const parts = lines[index].split(/[,\s]+/).filter(Boolean);

    if (parts.length !== 2) {
      return { points: [], error: `Line ${index + 1}: expected "latitude, longitude".` };
    }

    const lat = Number(parts[0]);
    const lng = Number(parts[1]);

    if (!Number.isFinite(lat) || Math.abs(lat) > 90) {
      return { points: [], error: `Line ${index + 1}: latitude must be between −90 and 90.` };
    }
    if (!Number.isFinite(lng) || Math.abs(lng) > 180) {
      return { points: [], error: `Line ${index + 1}: longitude must be between −180 and 180.` };
    }

    points.push([lat, lng]);
  }

  if (points.length < 3) {
    return { points, error: "A polygon needs at least three vertices." };
  }

  return { points, error: null };
}
