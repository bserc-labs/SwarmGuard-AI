/**
 * Telemetry socket provider.
 *
 * Owns one socket for the authenticated session and fans frames out to the app.
 * Two behaviours matter for correctness:
 *
 *  - Liveness is measured, not assumed. `lastMessageAt` ticks on every frame and
 *    drives the Live / Stale / Offline chip, so an open-but-silent socket reads
 *    as Stale rather than Live.
 *  - Frames are classified by shape. The backend publishes telemetry packets and
 *    alert payloads on the same channel with no discriminator field, so a packet
 *    is identified by the presence of numeric coordinates.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { createWebSocket, type TelemetrySocket, type WSConnectionState, type WSMessage } from "@/services/websocket";
import { deriveFeedState, type FeedState } from "@/lib/feedState";
import type { DetectionResult, TelemetryPacket } from "@/services/api";
import { isAuthenticated } from "@/services/auth";

const MAX_ALERTS = 100;

interface WebSocketContextValue {
  connectionState: WSConnectionState;
  feedState: FeedState;
  lastMessageAt: number | null;
  alerts: DetectionResult[];
  lastAlert: DetectionResult | null;
  latestTelemetry: Record<string, TelemetryPacket>;
  dismissAlert: () => void;
  reconnect: () => void;
}

const WebSocketContext = createContext<WebSocketContextValue | null>(null);

function isTelemetryFrame(data: WSMessage): boolean {
  return (
    typeof data.drone_id === "string" &&
    typeof data.latitude === "number" &&
    typeof data.longitude === "number"
  );
}

function isAlertFrame(data: WSMessage): boolean {
  return data.is_anomaly === true || typeof data.attack_type === "string";
}

export function WebSocketProvider({ children }: { children: ReactNode }) {
  const [connectionState, setConnectionState] = useState<WSConnectionState>("DISCONNECTED");
  const [lastMessageAt, setLastMessageAt] = useState<number | null>(null);
  const [alerts, setAlerts] = useState<DetectionResult[]>([]);
  const [lastAlert, setLastAlert] = useState<DetectionResult | null>(null);
  const [latestTelemetry, setLatestTelemetry] = useState<Record<string, TelemetryPacket>>({});
  const socketRef = useRef<TelemetrySocket | null>(null);

  const handleMessage = useCallback((data: WSMessage) => {
    setLastMessageAt(Date.now());

    if (isTelemetryFrame(data)) {
      const packet = data as unknown as TelemetryPacket;
      setLatestTelemetry((prev) => ({ ...prev, [packet.drone_id]: packet }));
      return;
    }

    if (isAlertFrame(data)) {
      const alert = data as unknown as DetectionResult;
      setLastAlert(alert);
      setAlerts((prev) => [alert, ...prev].slice(0, MAX_ALERTS));
    }
  }, []);

  useEffect(() => {
    // Without a token there is nothing to subscribe to. No state write is
    // needed: connectionState starts DISCONNECTED and feedState below reports
    // "unauthenticated" from isAuthenticated() directly.
    if (!isAuthenticated()) return;

    const socket = createWebSocket({
      onMessage: handleMessage,
      onStateChange: setConnectionState,
    });
    socketRef.current = socket;

    return () => {
      socket.disconnect();
      socketRef.current = null;
    };
  }, [handleMessage]);

  // Re-render on a timer so a feed that goes silent transitions Live -> Stale
  // without waiting for the next frame, which by definition may never arrive.
  const [, setTick] = useState(0);
  useEffect(() => {
    if (connectionState !== "CONNECTED") return;
    const id = setInterval(() => setTick((t) => t + 1), 5_000);
    return () => clearInterval(id);
  }, [connectionState]);

  const reconnect = useCallback(() => {
    socketRef.current?.disconnect();
    const socket = createWebSocket({
      onMessage: handleMessage,
      onStateChange: setConnectionState,
    });
    socketRef.current = socket;
  }, [handleMessage]);

  const dismissAlert = useCallback(() => setLastAlert(null), []);

  const feedState = isAuthenticated()
    ? deriveFeedState(connectionState, lastMessageAt)
    : "unauthenticated";

  const value = useMemo<WebSocketContextValue>(
    () => ({
      connectionState,
      feedState,
      lastMessageAt,
      alerts,
      lastAlert,
      latestTelemetry,
      dismissAlert,
      reconnect,
    }),
    [connectionState, feedState, lastMessageAt, alerts, lastAlert, latestTelemetry, dismissAlert, reconnect],
  );

  return <WebSocketContext.Provider value={value}>{children}</WebSocketContext.Provider>;
}

export function useWebSocketContext(): WebSocketContextValue {
  const ctx = useContext(WebSocketContext);
  if (!ctx) throw new Error("useWebSocketContext must be used within WebSocketProvider");
  return ctx;
}
