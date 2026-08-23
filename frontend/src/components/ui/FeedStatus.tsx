/**
 * Feed liveness indicator.
 *
 * The previous header showed a pulsing green "System Online" chip that was
 * hardcoded — it read online while the socket was closed. Liveness now comes
 * from `deriveFeedState`, which measures the connection state and the age of the
 * last frame. Only `live` animates: a pulsing dot means data is moving.
 */

import { FEED_PRESENTATION, type FeedState } from "@/lib/feedState";
import { cn } from "@/lib/utils";

export function FeedStatus({
  state,
  showLabel = true,
  className,
}: {
  state: FeedState;
  showLabel?: boolean;
  className?: string;
}) {
  const p = FEED_PRESENTATION[state];

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-chip border border-line-strong bg-surface-overlay px-2 py-1",
        className,
      )}
      title={p.description}
    >
      <span
        aria-hidden="true"
        className={cn("h-1.5 w-1.5 shrink-0 rounded-full", p.dot, p.pulse && "sg-live-dot")}
      />
      {showLabel ? (
        <span className={cn("text-[11px] font-medium leading-none", p.text)}>{p.label}</span>
      ) : null}
      <span className="sr-only">
        Telemetry feed: {p.label}. {p.description}
      </span>
    </span>
  );
}
