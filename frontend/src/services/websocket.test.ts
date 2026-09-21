/**
 * Telemetry socket behaviour.
 *
 * These cover the failure modes that matter operationally: a rejected token must
 * not retry forever, a dropped connection must back off and recover, and a
 * socket that is open but silent must be treated as stale rather than live.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { TelemetrySocket, type WSConnectionState } from "./websocket";
import { STORAGE_KEYS } from "@/config";

/** Minimal WebSocket double with manual control over lifecycle events. */
class MockWebSocket {
  static instances: MockWebSocket[] = [];

  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSING = 2;
  static readonly CLOSED = 3;

  readyState = MockWebSocket.CONNECTING;
  sent: string[] = [];

  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onclose: ((event: { code: number }) => void) | null = null;
  onerror: (() => void) | null = null;

  constructor(readonly url: string) {
    MockWebSocket.instances.push(this);
  }

  send(data: string) {
    this.sent.push(data);
  }

  close(code = 1000) {
    this.readyState = MockWebSocket.CLOSED;
    this.onclose?.({ code });
  }

  /* -- test helpers -- */
  open() {
    this.readyState = MockWebSocket.OPEN;
    this.onopen?.();
  }

  receive(payload: unknown) {
    this.onmessage?.({ data: JSON.stringify(payload) });
  }

  static latest(): MockWebSocket {
    const socket = MockWebSocket.instances.at(-1);
    if (!socket) throw new Error("No socket was constructed");
    return socket;
  }

  static reset() {
    MockWebSocket.instances = [];
  }
}

describe("TelemetrySocket", () => {
  let states: WSConnectionState[];

  beforeEach(() => {
    vi.useFakeTimers();
    MockWebSocket.reset();
    vi.stubGlobal("WebSocket", MockWebSocket);
    localStorage.setItem(STORAGE_KEYS.token, "test-token");
    states = [];
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  function build(overrides: Partial<ConstructorParameters<typeof TelemetrySocket>[0]> = {}) {
    return new TelemetrySocket({
      onMessage: () => {},
      onStateChange: (s) => states.push(s),
      ...overrides,
    });
  }

  it("goes offline without attempting a connection when no token is stored", () => {
    localStorage.clear();
    const socket = build();
    socket.connect();

    expect(MockWebSocket.instances).toHaveLength(0);
    expect(socket.getState()).toBe("OFFLINE");
  });

  it("includes the token in the handshake URL", () => {
    build().connect();
    expect(MockWebSocket.latest().url).toContain("token=test-token");
    expect(MockWebSocket.latest().url).toContain("/ws/telemetry");
  });

  it("reports CONNECTED once the socket opens", () => {
    const socket = build();
    socket.connect();
    MockWebSocket.latest().open();

    expect(socket.getState()).toBe("CONNECTED");
    expect(states).toEqual(["CONNECTING", "CONNECTED"]);
  });

  it("does not retry after a policy-violation close", () => {
    // 1008 is what the backend sends for a missing or invalid token. Retrying
    // cannot succeed and would hammer the endpoint.
    const socket = build();
    socket.connect();
    MockWebSocket.latest().open();
    MockWebSocket.latest().close(1008);

    expect(socket.getState()).toBe("OFFLINE");

    vi.advanceTimersByTime(60_000);
    expect(MockWebSocket.instances).toHaveLength(1);
  });

  it("backs off and reconnects after an unexpected close", () => {
    const socket = build();
    socket.connect();
    MockWebSocket.latest().open();
    MockWebSocket.latest().close(1006);

    expect(socket.getState()).toBe("RECONNECTING");
    expect(MockWebSocket.instances).toHaveLength(1);

    vi.advanceTimersByTime(2000);
    expect(MockWebSocket.instances).toHaveLength(2);
  });

  it("stops retrying once maxRetries is exhausted", () => {
    // Exhaustion requires attempts that never succeed. A socket that opens
    // resets the counter, which is why this loop never calls open().
    const socket = build({ maxRetries: 2 });
    socket.connect();

    for (let i = 0; i < 5; i += 1) {
      MockWebSocket.latest().close(1006);
      vi.advanceTimersByTime(30_000);
    }

    expect(socket.getState()).toBe("OFFLINE");
    expect(MockWebSocket.instances.length).toBeLessThanOrEqual(3);
  });

  it("resets the retry budget after a successful reconnect", () => {
    const socket = build({ maxRetries: 2 });
    socket.connect();

    // Two failures, then a success: the budget should be replenished.
    MockWebSocket.latest().close(1006);
    vi.advanceTimersByTime(30_000);
    MockWebSocket.latest().open();

    MockWebSocket.latest().close(1006);
    vi.advanceTimersByTime(30_000);
    MockWebSocket.latest().open();

    expect(socket.getState()).toBe("CONNECTED");
  });

  it("forwards decoded frames and records their arrival time", () => {
    const onMessage = vi.fn();
    const socket = build({ onMessage });
    socket.connect();
    MockWebSocket.latest().open();

    MockWebSocket.latest().receive({ drone_id: "UAV-1", latitude: 1, longitude: 2 });

    expect(onMessage).toHaveBeenCalledWith({ drone_id: "UAV-1", latitude: 1, longitude: 2 });
    expect(socket.getLastMessageAt()).not.toBeNull();
  });

  it("swallows frames that are not valid JSON", () => {
    const onMessage = vi.fn();
    build({ onMessage }).connect();
    MockWebSocket.latest().open();
    MockWebSocket.latest().onmessage?.({ data: "not json" });

    expect(onMessage).not.toHaveBeenCalled();
  });

  it("does not forward pong keepalives to the application", () => {
    const onMessage = vi.fn();
    build({ onMessage }).connect();
    MockWebSocket.latest().open();
    MockWebSocket.latest().receive({ type: "pong" });

    expect(onMessage).not.toHaveBeenCalled();
  });

  it("closes a socket that stops producing traffic", () => {
    build({ pingIntervalMs: 1000, staleAfterMs: 5000 }).connect();
    const ws = MockWebSocket.latest();
    ws.open();

    // Within the window: the heartbeat pings rather than closing.
    vi.advanceTimersByTime(3000);
    expect(ws.readyState).toBe(MockWebSocket.OPEN);
    expect(ws.sent.length).toBeGreaterThan(0);

    // Past the window with no inbound frame: drop it so backoff reconnects.
    vi.advanceTimersByTime(4000);
    expect(ws.readyState).toBe(MockWebSocket.CLOSED);
  });

  it("stays open while frames keep arriving", () => {
    build({ pingIntervalMs: 1000, staleAfterMs: 5000 }).connect();
    const ws = MockWebSocket.latest();
    ws.open();

    for (let i = 0; i < 8; i += 1) {
      vi.advanceTimersByTime(1000);
      ws.receive({ drone_id: "UAV-1", latitude: 1, longitude: 2 });
    }

    expect(ws.readyState).toBe(MockWebSocket.OPEN);
  });

  it("sends a JSON ping on each heartbeat tick", () => {
    // The backend answers exactly this frame (routers/websocket.py _is_ping);
    // changing it is a wire-format change, not a refactor.
    build({ pingIntervalMs: 1000, staleAfterMs: 5000 }).connect();
    const ws = MockWebSocket.latest();
    ws.open();

    vi.advanceTimersByTime(1000);
    expect(ws.sent).toEqual([JSON.stringify({ type: "ping" })]);
  });

  it("treats a pong as liveness so an idle feed stays connected", () => {
    // No telemetry at all -- the normal state between sorties -- only the
    // backend's pong replies, for four times the stale window. The backend
    // used to send nothing back, so this socket tore itself down and
    // reconnected every ~31 s for as long as the dashboard was open.
    const onMessage = vi.fn();
    build({ onMessage, pingIntervalMs: 1000, staleAfterMs: 5000 }).connect();
    const ws = MockWebSocket.latest();
    ws.open();

    for (let i = 0; i < 20; i += 1) {
      vi.advanceTimersByTime(1000);
      ws.receive({ type: "pong" });
    }

    expect(ws.readyState).toBe(MockWebSocket.OPEN);
    expect(states.at(-1)).toBe("CONNECTED");
    expect(MockWebSocket.instances).toHaveLength(1); // never reconnected
    expect(onMessage).not.toHaveBeenCalled(); // pongs never reach the app
  });

  it("does not reconnect after an intentional disconnect", () => {
    const socket = build();
    socket.connect();
    MockWebSocket.latest().open();

    socket.disconnect();
    expect(socket.getState()).toBe("OFFLINE");

    vi.advanceTimersByTime(60_000);
    expect(MockWebSocket.instances).toHaveLength(1);
  });

  it("ignores a duplicate connect while a socket is already live", () => {
    const socket = build();
    socket.connect();
    MockWebSocket.latest().open();
    socket.connect();

    expect(MockWebSocket.instances).toHaveLength(1);
  });
});
