/**
 * Feed liveness derivation.
 *
 * This is the rule that replaced the hardcoded "System Online" chip, so it is
 * worth pinning down: connected-but-silent must never read as live.
 */

import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { FeedStatus } from "./FeedStatus";
import { deriveFeedState } from "@/lib/feedState";

const NOW = 1_700_000_000_000;
const STALE_AFTER = 15_000;

describe("deriveFeedState", () => {
  it("is live when a frame arrived inside the freshness window", () => {
    expect(deriveFeedState("CONNECTED", NOW - 5_000, NOW, STALE_AFTER)).toBe("live");
  });

  it("is stale when connected but the last frame is older than the window", () => {
    expect(deriveFeedState("CONNECTED", NOW - 60_000, NOW, STALE_AFTER)).toBe("stale");
  });

  it("is stale when connected but no frame has ever arrived", () => {
    // An open socket is not evidence of a working feed.
    expect(deriveFeedState("CONNECTED", null, NOW, STALE_AFTER)).toBe("stale");
  });

  it("treats the window boundary as still live", () => {
    expect(deriveFeedState("CONNECTED", NOW - STALE_AFTER, NOW, STALE_AFTER)).toBe("live");
  });

  it("reports connecting during handshake and backoff", () => {
    expect(deriveFeedState("CONNECTING", null, NOW, STALE_AFTER)).toBe("connecting");
    expect(deriveFeedState("RECONNECTING", NOW, NOW, STALE_AFTER)).toBe("connecting");
  });

  it("reports offline when closed, even if a frame arrived a moment ago", () => {
    expect(deriveFeedState("OFFLINE", NOW, NOW, STALE_AFTER)).toBe("offline");
    expect(deriveFeedState("DISCONNECTED", NOW, NOW, STALE_AFTER)).toBe("offline");
  });
});

describe("FeedStatus", () => {
  it("labels each state and describes it for assistive technology", () => {
    render(<FeedStatus state="live" />);
    expect(screen.getByText("Live")).toBeInTheDocument();
    expect(screen.getByText(/Receiving telemetry frames/)).toBeInTheDocument();
  });

  it("keeps an accessible description when the visible label is hidden", () => {
    render(<FeedStatus state="offline" showLabel={false} />);
    expect(screen.queryByText("Offline")).not.toBeInTheDocument();
    expect(screen.getByText(/Telemetry feed: Offline/)).toBeInTheDocument();
  });

  it("animates only the live state", () => {
    const { container: live } = render(<FeedStatus state="live" />);
    expect(live.querySelector(".sg-live-dot")).not.toBeNull();

    const { container: stale } = render(<FeedStatus state="stale" />);
    expect(stale.querySelector(".sg-live-dot")).toBeNull();
  });
});
