import { getToken } from "./auth";

type MessageHandler = (data: unknown) => void;
type StatusHandler = (connected: boolean) => void;

interface WSOptions {
  onMessage: MessageHandler;
  onStatusChange?: StatusHandler;
  reconnectInterval?: number;
  maxRetries?: number;
}

export function createWebSocket(options: WSOptions) {
  const { onMessage, onStatusChange, reconnectInterval = 5000, maxRetries = 10 } = options;
  let ws: WebSocket | null = null;
  let retries = 0;
  let intentionalClose = false;

  function connect() {
    const token = getToken();
    if (!token) {
      console.warn("[WS] No auth token, skipping connection");
      return;
    }

    ws = new WebSocket(`ws://localhost:8000/ws/telemetry?token=${token}`);

    ws.onopen = () => {
      console.log("[WS] Connected to telemetry stream");
      retries = 0;
      onStatusChange?.(true);
    };

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        onMessage(data);
      } catch {
        console.warn("[WS] Failed to parse message:", event.data);
      }
    };

    ws.onclose = (event) => {
      console.log(`[WS] Disconnected (code: ${event.code})`);
      onStatusChange?.(false);

      if (!intentionalClose && retries < maxRetries) {
        retries++;
        console.log(`[WS] Reconnecting in ${reconnectInterval / 1000}s (attempt ${retries}/${maxRetries})`);
        setTimeout(connect, reconnectInterval);
      }
    };

    ws.onerror = (error) => {
      console.error("[WS] Error:", error);
    };
  }

  function disconnect() {
    intentionalClose = true;
    ws?.close();
    ws = null;
  }

  function send(data: unknown) {
    if (ws?.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(data));
    }
  }

  connect();

  return { disconnect, send };
}
