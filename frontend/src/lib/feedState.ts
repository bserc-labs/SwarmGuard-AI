/**
 * Feed liveness derivation.
 *
 * Kept apart from the component that renders it so the rule can be imported by
 * non-component modules (and so the file stays fast-refresh clean).
 */

import { TELEMETRY_STALE_AFTER_MS } from "@/config";
import type { WSConnectionState } from "@/services/websocket";

export type FeedState = "live" | "stale" | "connecting" | "offline" | "unauthenticated";

export function deriveFeedState(
  connectionState: WSConnectionState,
  lastMessageAt: number | null,
  now: number = Date.now(),
  staleAfterMs: number = TELEMETRY_STALE_AFTER_MS,
): FeedState {
  switch (connectionState) {
    case "CONNECTING":
    case "RECONNECTING":
      return "connecting";
    case "DISCONNECTED":
    case "OFFLINE":
      return "offline";
    case "CONNECTED":
      // Connected but nothing has arrived yet, or not recently: not live.
      if (lastMessageAt === null) return "stale";
      return now - lastMessageAt <= staleAfterMs ? "live" : "stale";
  }
}

export const FEED_PRESENTATION: Record<
  FeedState,
  { label: string; dot: string; text: string; description: string; pulse: boolean }
> = {
  live: {
    label: "Live",
    dot: "bg-nominal",
    text: "text-nominal",
    description: "Receiving telemetry frames.",
    pulse: true,
  },
  stale: {
    label: "Stale",
    dot: "bg-warning",
    text: "text-warning",
    description: "Connected, but no frames have arrived recently.",
    pulse: false,
  },
  connecting: {
    label: "Connecting",
    dot: "bg-content-dim",
    text: "text-content-muted",
    description: "Establishing the telemetry stream.",
    pulse: false,
  },
  offline: {
    label: "Offline",
    dot: "bg-critical",
    text: "text-critical",
    description: "No telemetry stream. Values shown are from the last poll.",
    pulse: false,
  },
  unauthenticated: {
    label: "Signed out",
    dot: "bg-content-dim",
    text: "text-content-dim",
    description: "Sign in to receive telemetry.",
    pulse: false,
  },
};

export function feedStateDescription(state: FeedState): string {
  return FEED_PRESENTATION[state].description;
}
