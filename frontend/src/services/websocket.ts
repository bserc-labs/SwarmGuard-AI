/**
 * Telemetry socket transport.
 *
 * The connection state machine, exponential backoff, stale-traffic detection and
 * duplicate-subscription guard are preserved from the original implementation.
 * Changes: the URL is derived from config rather than window.location directly,
 * and the manager now reports when it last received traffic so the UI can
 * distinguish a live feed from an open-but-silent socket.
 */

import { telemetrySocketUrl } from "@/config";
import { getToken } from "./auth";

export type WSConnectionState =
  | "CONNECTING"
  | "CONNECTED"
  | "DISCONNECTED"
  | "RECONNECTING"
  | "OFFLINE";

export type WSMessage = Record<string, unknown>;

type MessageHandler = (data: WSMessage) => void;
type StateHandler = (state: WSConnectionState) => void;

export interface WSOptions {
  onMessage: MessageHandler;
  onStateChange?: StateHandler;
  reconnectInterval?: number;
  maxRetries?: number;
  pingIntervalMs?: number;
  /** Close and reconnect if no frame arrives within this window. */
  staleAfterMs?: number;
}

const DEFAULTS = {
  reconnectInterval: 3000,
  maxRetries: 10,
  pingIntervalMs: 15_000,
  staleAfterMs: 30_000,
} as const;

export class TelemetrySocket {
  private ws: WebSocket | null = null;
  private readonly options: Required<WSOptions>;
  private retries = 0;
  private intentionalClose = false;
  private pingTimer: ReturnType<typeof setInterval> | null = null;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private lastMessageAt: number | null = null;
  private state: WSConnectionState = "DISCONNECTED";

  constructor(options: WSOptions) {
    this.options = { ...DEFAULTS, onStateChange: () => {}, ...options };
  }

  connect(): void {
    const token = getToken();
    if (!token) {
      // Not authenticated: there is nothing to subscribe to.
      this.updateState("OFFLINE");
      return;
    }

    if (
      this.ws &&
      (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)
    ) {
      return; // already connected or connecting
    }

    this.intentionalClose = false;
    this.updateState(this.retries > 0 ? "RECONNECTING" : "CONNECTING");

    // The backend reads the token from the query string. nginx no longer logs
    // the /ws/ request line and the backend redacts it from its own access
    // log, but a credential in a URL is still one proxy misconfiguration away
    // from a log file. Tracked for removal from the URL.
    const url = `${telemetrySocketUrl()}?token=${encodeURIComponent(token)}`;

    try {
      this.ws = new WebSocket(url);
    } catch {
      this.scheduleReconnect();
      return;
    }

    this.ws.onopen = () => {
      this.retries = 0;
      this.lastMessageAt = Date.now();
      this.updateState("CONNECTED");
      this.startHeartbeat();
    };

    this.ws.onmessage = (event: MessageEvent<string>) => {
      this.lastMessageAt = Date.now();
      let data: WSMessage;
      try {
        data = JSON.parse(event.data) as WSMessage;
      } catch {
        return; // non-JSON frame; nothing downstream can use it
      }
      if (data.type === "pong" || data.event === "pong") return;
      this.options.onMessage(data);
    };

    this.ws.onclose = (event: CloseEvent) => {
      this.stopHeartbeat();
      this.ws = null;

      if (this.intentionalClose) {
        this.updateState("OFFLINE");
        return;
      }

      // 1008 is the policy-violation code the backend sends for a missing or
      // invalid token. Retrying cannot fix that, so stop rather than loop.
      if (event.code === 1008) {
        this.updateState("OFFLINE");
        return;
      }

      this.updateState("DISCONNECTED");
      this.scheduleReconnect();
    };

    this.ws.onerror = () => {
      // onclose always follows; recovery is handled there.
    };
  }

  private scheduleReconnect(): void {
    if (this.reconnectTimer) return;

    if (this.retries >= this.options.maxRetries) {
      this.updateState("OFFLINE");
      return;
    }

    this.retries += 1;
    const delay = Math.min(1000 * Math.pow(1.5, this.retries), 15_000);
    this.updateState("RECONNECTING");
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.connect();
    }, delay);
  }

  private startHeartbeat(): void {
    this.stopHeartbeat();
    this.pingTimer = setInterval(() => {
      if (this.ws?.readyState !== WebSocket.OPEN) return;

      if (this.lastMessageAt !== null && Date.now() - this.lastMessageAt > this.options.staleAfterMs) {
        // Open but silent — drop it so the backoff path re-establishes a fresh socket.
        this.ws.close();
        return;
      }

      try {
        this.ws.send(JSON.stringify({ type: "ping" }));
      } catch {
        /* the close handler will pick this up */
      }
    }, this.options.pingIntervalMs);
  }

  private stopHeartbeat(): void {
    if (this.pingTimer) {
      clearInterval(this.pingTimer);
      this.pingTimer = null;
    }
  }

  disconnect(): void {
    this.intentionalClose = true;
    this.stopHeartbeat();
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
    this.updateState("OFFLINE");
  }

  send(data: unknown): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(data));
    }
  }

  private updateState(next: WSConnectionState): void {
    if (this.state === next) return;
    this.state = next;
    this.options.onStateChange(next);
  }

  getState(): WSConnectionState {
    return this.state;
  }

  /** Epoch ms of the last frame received, or null if none has arrived. */
  getLastMessageAt(): number | null {
    return this.lastMessageAt;
  }
}

/** Construct and immediately connect. Retained for call-site compatibility. */
export function createWebSocket(options: WSOptions): TelemetrySocket {
  const socket = new TelemetrySocket(options);
  socket.connect();
  return socket;
}
