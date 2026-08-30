/**
 * DVR playback control.
 *
 * Scrubs backwards through recorded telemetry via GET /telemetry/history.
 * Behaviour is preserved from the original scrubber; the presentation is rebuilt
 * and the emoji status markers are gone.
 *
 * Note for operators: the backend prunes telemetry older than three days, so
 * scrubbing beyond the retention window returns nothing. That is reported as an
 * empty window rather than silently showing the live positions.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError, type TelemetryRecord } from "@/services/api";
import { Icon } from "@/components/ui/Icon";
import { Mono } from "@/components/ui/primitives";
import { cn } from "@/lib/utils";

type FetchStatus = "idle" | "loading" | "empty" | "error";

const MAX_OFFSET_MINUTES = 60;
/** Half-width of the snapshot window sampled around the target instant. */
const WINDOW_MS = 10_000;
const DEBOUNCE_MS = 400;

export function DvrPlayback({
  onFrameChange,
  className,
}: {
  /** Receives the recorded snapshot, or null to return to the live feed. */
  onFrameChange: (records: TelemetryRecord[] | null) => void;
  className?: string;
}) {
  const [active, setActive] = useState(false);
  const [offsetMinutes, setOffsetMinutes] = useState(0);
  const [fetchState, setFetchState] = useState<{
    status: FetchStatus;
    message: string | null;
  }>({ status: "idle", message: null });

  const scrubbing = active && offsetMinutes !== 0;
  // Fetch state only means something while scrubbing; derive rather than reset.
  const status = scrubbing ? fetchState.status : "idle";
  const message = scrubbing ? fetchState.message : null;

  // Stable identity so the fetch effect does not re-run on every render.
  const setStatus = useCallback(
    (next: FetchStatus, text: string | null = null) =>
      setFetchState({ status: next, message: text }),
    [],
  );

  // Held in a ref so changing the callback identity does not retrigger the fetch.
  const onFrameChangeRef = useRef(onFrameChange);
  useEffect(() => {
    onFrameChangeRef.current = onFrameChange;
  }, [onFrameChange]);

  useEffect(() => {
    if (!scrubbing) {
      onFrameChangeRef.current(null);
      return;
    }

    let cancelled = false;

    const timer = setTimeout(async () => {
      setStatus("loading");
      const target = new Date(Date.now() - Math.abs(offsetMinutes) * 60_000);
      const start = new Date(target.getTime() - WINDOW_MS);
      const end = new Date(target.getTime() + WINDOW_MS);

      try {
        const rows = await api.getTelemetryHistory(start.toISOString(), end.toISOString(), {
          limit: 2000,
        });
        if (cancelled) return;

        // Keep the newest row per drone inside the window.
        const newest = new Map<string, TelemetryRecord>();
        for (const row of rows) newest.set(row.drone_id, row);
        const snapshot = [...newest.values()];

        if (snapshot.length === 0) {
          setStatus("empty", "No telemetry recorded at this time.");
          onFrameChangeRef.current([]);
          return;
        }

        setStatus("idle");
        onFrameChangeRef.current(snapshot);
      } catch (error) {
        if (cancelled) return;
        setStatus(
          "error",
          error instanceof ApiError && error.isForbidden
            ? "You do not have permission to read telemetry history."
            : "Could not load recorded telemetry.",
        );
      }
    }, DEBOUNCE_MS);

    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [scrubbing, offsetMinutes, setStatus]);

  const toggle = useCallback(() => {
    setActive((prev) => {
      if (prev) setOffsetMinutes(0);
      return !prev;
    });
  }, []);

  const label = offsetMinutes === 0 ? "Live" : `${Math.abs(offsetMinutes)} min ago`;

  return (
    <div
      className={cn(
        "rounded-panel border border-line bg-surface-raised/95 p-3 backdrop-blur-sm",
        className,
      )}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <button
          type="button"
          onClick={toggle}
          aria-pressed={active}
          className={cn(
            "inline-flex h-7 items-center gap-1.5 rounded-control border px-2.5 text-[12px] font-medium transition-colors",
            active
              ? "border-warning/40 bg-warning-wash text-warning"
              : "border-line-strong bg-surface-overlay text-content hover:bg-surface-hover",
          )}
        >
          <Icon name={active ? "pause" : "play"} size={13} />
          {active ? "Replaying" : "Replay"}
        </button>

        <div className="flex items-center gap-2">
          {status === "loading" ? (
            <span className="text-[11px] text-content-dim">Loading…</span>
          ) : null}
          <Mono className={cn(status === "empty" ? "text-warning" : "text-content-muted")}>
            {label}
          </Mono>
        </div>
      </div>

      <div className={cn("mt-2.5", !active && "pointer-events-none opacity-40")}>
        <label htmlFor="dvr-scrub" className="sr-only">
          Playback position, minutes before now
        </label>
        <input
          id="dvr-scrub"
          type="range"
          min={-MAX_OFFSET_MINUTES}
          max={0}
          step={1}
          value={offsetMinutes}
          disabled={!active}
          onChange={(e) => setOffsetMinutes(Number(e.target.value))}
          aria-valuetext={label}
          className="h-1.5 w-full cursor-pointer appearance-none rounded-full bg-surface-active"
        />
        <div className="mt-1 flex justify-between text-[11px] text-content-dim">
          <span>−60 min</span>
          <span>−30 min</span>
          <span>Now</span>
        </div>
      </div>

      {message ? (
        <p
          className={cn(
            "mt-2 text-[11px]",
            status === "error" ? "text-critical" : "text-content-muted",
          )}
        >
          {message}
        </p>
      ) : null}
    </div>
  );
}
