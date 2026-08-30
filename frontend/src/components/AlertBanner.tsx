/**
 * Live alert banner.
 *
 * Surfaces high and critical alerts arriving over the socket. Two truth rules
 * apply here specifically, because this is the component most likely to
 * overstate what the backend knows:
 *
 *  - Feature attribution is shown only when the payload carries a usable
 *    magnitude. The previous version read `.value` while the producer writes
 *    `.importance`, so it rendered "NaN%" as a confident finding.
 *  - The score is labelled "threat level" — the field the backend actually
 *    sends — not "AI confidence" or "verified score".
 */

import { useEffect, useState } from "react";
import { Link } from "@tanstack/react-router";
import { useWebSocketContext } from "@/contexts/WebSocketContext";
import { Icon } from "@/components/ui/Icon";
import { Chip, Mono } from "@/components/ui/primitives";
import { attributionMagnitude, humanizeEnum } from "@/lib/format";
import { severityTone } from "@/lib/constants";
import type { DetectionResult } from "@/services/api";

const DISMISS_AFTER_MS = 12_000;

function topAttribution(alert: DetectionResult): { feature: string; magnitude: number } | null {
  const entries = alert.shap_top3;
  if (!entries?.length) return null;

  const first = entries[0];
  const magnitude = attributionMagnitude(first);
  if (first.feature === undefined || magnitude === null) return null;

  // Magnitudes are expected as a 0-1 fraction. Anything else is not
  // interpretable as a contribution share, so it is withheld.
  if (magnitude < 0 || magnitude > 1) return null;

  return { feature: first.feature, magnitude };
}

function isEscalated(alert: DetectionResult | null): boolean {
  const severity = alert?.severity?.toUpperCase();
  return severity === "CRITICAL" || severity === "HIGH";
}

export function AlertBanner() {
  const { lastAlert, dismissAlert } = useWebSocketContext();
  // Which alert the operator has already seen. Derived visibility rather than
  // mirrored state, so a new alert cannot be missed by a stale effect.
  const [dismissed, setDismissed] = useState<DetectionResult | null>(null);

  const alert = isEscalated(lastAlert) ? lastAlert : null;
  const visible = alert !== null && alert !== dismissed;

  // Auto-dismiss. The state write happens in the timer callback, not the body.
  useEffect(() => {
    if (!visible || !alert) return;
    const timer = setTimeout(() => setDismissed(alert), DISMISS_AFTER_MS);
    return () => clearTimeout(timer);
  }, [visible, alert]);

  if (!visible || !alert) return null;

  const isCritical = alert.severity?.toUpperCase() === "CRITICAL";
  const attribution = topAttribution(alert);

  const close = () => {
    setDismissed(alert);
    dismissAlert();
  };

  return (
    <div
      role="alert"
      aria-live="assertive"
      className="sg-enter border-b border-line bg-surface-overlay px-3 py-2.5 sm:px-5"
    >
      <div className="flex flex-wrap items-start gap-x-3 gap-y-2">
        <Icon
          name="alert"
          size={16}
          className={`mt-0.5 shrink-0 ${isCritical ? "text-critical" : "text-warning"}`}
        />

        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <p className="text-[13px] font-semibold text-content">
              {humanizeEnum(alert.attack_type) || "Anomaly"}
              {alert.drone_id ? (
                <>
                  {" on "}
                  <Mono className="text-content-muted">{alert.drone_id}</Mono>
                </>
              ) : null}
            </p>
            {alert.severity ? (
              <Chip tone={severityTone(alert.severity)}>{humanizeEnum(alert.severity)}</Chip>
            ) : null}
            {alert.threat_level !== null && alert.threat_level !== undefined ? (
              <span className="text-[12px] text-content-muted">
                Threat level <span className="tabular text-content">{alert.threat_level}</span>/100
              </span>
            ) : null}
          </div>

          {alert.explanation ? (
            <p className="mt-1 max-w-[80ch] text-[12px] leading-relaxed text-content-muted">
              {alert.explanation}
            </p>
          ) : null}

          {attribution ? (
            <p className="mt-1 text-[12px] text-content-dim">
              Largest contributor:{" "}
              <Mono className="text-content-muted">{attribution.feature}</Mono>{" "}
              <span className="tabular">({Math.round(attribution.magnitude * 100)}%)</span>
            </p>
          ) : null}
        </div>

        <div className="flex shrink-0 items-center gap-2">
          <Link
            to="/incidents"
            onClick={close}
            className="rounded-control border border-line-strong bg-surface-raised px-2.5 py-1 text-[12px] text-content hover:bg-surface-hover"
          >
            View incidents
          </Link>
          <button
            type="button"
            onClick={close}
            className="flex h-7 w-7 items-center justify-center rounded-control text-content-dim hover:bg-surface-hover hover:text-content"
          >
            <Icon name="close" size={15} title="Dismiss alert" />
          </button>
        </div>
      </div>
    </div>
  );
}
