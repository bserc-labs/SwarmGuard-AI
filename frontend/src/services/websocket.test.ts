/**
 * Telemetry socket behaviour.
 *
 * These cover the failure modes that matter operationally: a rejected token must
 * not retry forever, a dropped connection must back off and recover, and a
 * socket that is open but silent must be treated as stale rather than live.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { TelemetrySocket, type WSConnectionState } from "./websocket";
import { api } from "./api";
import { STORAGE_KEYS } from "@/config";

// The client fetches a single-use ticket over HTTPS before it opens the
// socket, so the session token never reaches the URL. These tests care about
// socket behaviour, not about how the ticket was obtained.
vi.mock("./api", () => ({
  api: { getSocketTicket: vi.fn() },
}));

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
    vi.mocked(api.getSocketTicket).mockResolvedValue({ ticket: "test-ticket", expires_in: 30 });
    states = [];
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  /** connect(), plus the tick the ticket request needs to resolve. */
  async function connected(socket: TelemetrySocket): Promise<TelemetrySocket> {
    socket.connect();
    await vi.advanceTimersByTimeAsync(0);
    return socket;
  }

  function build(overrides: Partial<ConstructorParameters<typeof TelemetrySocket>[0]> = {}) {
    return new TelemetrySocket({
      onMessage: () => {},
      onStateChange: (s) => states.push(s),
      ...overrides,
    });
  }

  it("goes offline without attempting a connection when no token is stored", async () => {
    localStorage.clear();
    const socket = build();
    await connected(socket);

    expect(MockWebSocket.instances).toHaveLength(0);
    expect(socket.getState()).toBe("OFFLINE");
  });

  it("opens with a single-use ticket and never the session token", async () => {
    // The token used to travel in this URL, where proxy logs and browser
    // history keep it. A ticket lives half a minute and opens one socket.
    await connected(build());

    const { url } = MockWebSocket.latest();
    expect(url).toContain("/ws/telemetry");
    expect(url).toContain("ticket=test-ticket");
    expect(url).not.toContain("test-token");
  });

  it("asks for a fresh ticket on every connection", async () => {
    // A ticket is spent by the socket it opens, so a reconnect needs its own.
    const socket = await connected(build());
    MockWebSocket.latest().open();
    MockWebSocket.latest().close(1006);
    await vi.advanceTimersByTimeAsync(2000);

    expect(api.getSocketTicket).toHaveBeenCalledTimes(2);
    expect(MockWebSocket.instances).toHaveLength(2);
    expect(socket.getState()).not.toBe("OFFLINE");
  });

  it("retries rather than opening a socket when the ticket cannot be minted", async () => {
    vi.mocked(api.getSocketTicket).mockRejectedValueOnce(new Error("offline"));
    const socket = build();

    await connected(socket);

    expect(MockWebSocket.instances).toHaveLength(0);
    expect(socket.getState()).toBe("RECONNECTING");

    await vi.advanceTimersByTimeAsync(2000);
    expect(MockWebSocket.instances).toHaveLength(1);
  });

  it("reports CONNECTED once the socket opens", async () => {
    const socket = build();
    await connected(socket);
    MockWebSocket.latest().open();

    expect(socket.getState()).toBe("CONNECTED");
    expect(states).toEqual(["CONNECTING", "CONNECTED"]);
  });

  it("does not retry after a policy-violation close", async () => {
    // 1008 is what the backend sends for a missing or invalid token. Retrying
    // cannot succeed and would hammer the endpoint.
    const socket = build();
    await connected(socket);
    MockWebSocket.latest().open();
    MockWebSocket.latest().close(1008);

    expect(socket.getState()).toBe("OFFLINE");

    await vi.advanceTimersByTimeAsync(60_000);
    expect(MockWebSocket.instances).toHaveLength(1);
  });

  it("backs off and reconnects after an unexpected close", async () => {
    const socket = build();
    await connected(socket);
    MockWebSocket.latest().open();
    MockWebSocket.latest().close(1006);

    expect(socket.getState()).toBe("RECONNECTING");
    expect(MockWebSocket.instances).toHaveLength(1);

    await vi.advanceTimersByTimeAsync(2000);
    expect(MockWebSocket.instances).toHaveLength(2);
  });

  it("stops retrying once maxRetries is exhausted", async () => {
    // Exhaustion requires attempts that never succeed. A socket that opens
    // resets the counter, which is why this loop never calls open().
    const socket = build({ maxRetries: 2 });
    await connected(socket);

    for (let i = 0; i < 5; i += 1) {
      MockWebSocket.latest().close(1006);
      await vi.advanceTimersByTimeAsync(30_000);
    }

    expect(socket.getState()).toBe("OFFLINE");
    expect(MockWebSocket.instances.length).toBeLessThanOrEqual(3);
  });

  it("resets the retry budget after a successful reconnect", async () => {
    const socket = build({ maxRetries: 2 });
    await connected(socket);

    // Two failures, then a success: the budget should be replenished.
    MockWebSocket.latest().close(1006);
    await vi.advanceTimersByTimeAsync(30_000);
    MockWebSocket.latest().open();

    MockWebSocket.latest().close(1006);
    await vi.advanceTimersByTimeAsync(30_000);
    MockWebSocket.latest().open();

    expect(socket.getState()).toBe("CONNECTED");
  });

  it("forwards decoded frames and records their arrival time", async () => {
    const onMessage = vi.fn();
    const socket = build({ onMessage });
    await connected(socket);
    MockWebSocket.latest().open();

    MockWebSocket.latest().receive({ drone_id: "UAV-1", latitude: 1, longitude: 2 });

    expect(onMessage).toHaveBeenCalledWith({ drone_id: "UAV-1", latitude: 1, longitude: 2 });
    expect(socket.getLastMessageAt()).not.toBeNull();
  });

  it("swallows frames that are not valid JSON", async () => {
    const onMessage = vi.fn();
    await connected(build({ onMessage }));
    MockWebSocket.latest().open();
    MockWebSocket.latest().onmessage?.({ data: "not json" });

    expect(onMessage).not.toHaveBeenCalled();
  });

  it("does not forward pong keepalives to the application", async () => {
    const onMessage = vi.fn();
    await connected(build({ onMessage }));
    MockWebSocket.latest().open();
    MockWebSocket.latest().receive({ type: "pong" });

    expect(onMessage).not.toHaveBeenCalled();
  });

  it("closes a socket that stops producing traffic", async () => {
    await connected(build({ pingIntervalMs: 1000, staleAfterMs: 5000 }));
    const ws = MockWebSocket.latest();
    ws.open();

    // Within the window: the heartbeat pings rather than closing.
    await vi.advanceTimersByTimeAsync(3000);
    expect(ws.readyState).toBe(MockWebSocket.OPEN);
    expect(ws.sent.length).toBeGreaterThan(0);

    // Past the window with no inbound frame: drop it so backoff reconnects.
    await vi.advanceTimersByTimeAsync(4000);
    expect(ws.readyState).toBe(MockWebSocket.CLOSED);
  });

  it("stays open while frames keep arriving", async () => {
    await connected(build({ pingIntervalMs: 1000, staleAfterMs: 5000 }));
    const ws = MockWebSocket.latest();
    ws.open();

    for (let i = 0; i < 8; i += 1) {
      await vi.advanceTimersByTimeAsync(1000);
      ws.receive({ drone_id: "UAV-1", latitude: 1, longitude: 2 });
    }

    expect(ws.readyState).toBe(MockWebSocket.OPEN);
  });

  it("sends a JSON ping on each heartbeat tick", async () => {
    // The backend answers exactly this frame (routers/websocket.py _is_ping);
    // changing it is a wire-format change, not a refactor.
    await connected(build({ pingIntervalMs: 1000, staleAfterMs: 5000 }));
    const ws = MockWebSocket.latest();
    ws.open();

    await vi.advanceTimersByTimeAsync(1000);
    expect(ws.sent).toEqual([JSON.stringify({ type: "ping" })]);
  });

  it("treats a pong as liveness so an idle feed stays connected", async () => {
    // No telemetry at all -- the normal state between sorties -- only the
    // backend's pong replies, for four times the stale window. The backend
    // used to send nothing back, so this socket tore itself down and
    // reconnected every ~31 s for as long as the dashboard was open.
    const onMessage = vi.fn();
    await connected(build({ onMessage, pingIntervalMs: 1000, staleAfterMs: 5000 }));
    const ws = MockWebSocket.latest();
    ws.open();

    for (let i = 0; i < 20; i += 1) {
      await vi.advanceTimersByTimeAsync(1000);
      ws.receive({ type: "pong" });
    }

    expect(ws.readyState).toBe(MockWebSocket.OPEN);
    expect(states.at(-1)).toBe("CONNECTED");
    expect(MockWebSocket.instances).toHaveLength(1); // never reconnected
    expect(onMessage).not.toHaveBeenCalled(); // pongs never reach the app
  });

  it("does not reconnect after an intentional disconnect", async () => {
    const socket = build();
    await connected(socket);
    MockWebSocket.latest().open();

    socket.disconnect();
    expect(socket.getState()).toBe("OFFLINE");

    await vi.advanceTimersByTimeAsync(60_000);
    expect(MockWebSocket.instances).toHaveLength(1);
  });

  it("ignores a duplicate connect while a socket is already live", async () => {
    const socket = build();
    await connected(socket);
    MockWebSocket.latest().open();
    await connected(socket);  // duplicate connect

    expect(MockWebSocket.instances).toHaveLength(1);
  });
});
