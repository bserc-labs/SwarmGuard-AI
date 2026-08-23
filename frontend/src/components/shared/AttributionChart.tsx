/**
 * Feature attribution for an incident.
 *
 * Truth rules enforced here, because this component is the one most likely to
 * overstate what the model actually produced:
 *
 *  1. Nothing renders unless the incident carries attribution values. The
 *     previous version fell back to a default model version of "v1.0" when the
 *     payload had none, which presented an unverified guess as provenance.
 *  2. The heading says "reported by the detection model", not "SHAP-explained"
 *     or "AI-verified". The payload does not identify its explainer, so the UI
 *     does not name one — it shows `model_version` only when present.
 *  3. Entries whose magnitude key is missing or out of range are dropped rather
 *     than coerced to zero.
 */

import { useMemo } from "react";
import { Bar, BarChart, Cell, ResponsiveContainer, XAxis, YAxis } from "recharts";
import type { Incident } from "@/services/api";
import { UnavailableState } from "@/components/ui/DataState";
import { Chip, Mono } from "@/components/ui/primitives";
import { attributionMagnitude, humanizeEnum, num } from "@/lib/format";

interface Row {
  feature: string;
  magnitude: number;
  share: number;
}

function buildRows(incident: Incident): Row[] {
  const entries = incident.shap_values ?? [];

  const usable = entries
    .map((entry) => {
      const magnitude = attributionMagnitude(entry);
      if (!entry.feature || magnitude === null || !Number.isFinite(magnitude)) return null;
      return { feature: entry.feature, magnitude: Math.abs(magnitude) };
    })
    .filter((e): e is { feature: string; magnitude: number } => e !== null);

  if (usable.length === 0) return [];

  const total = usable.reduce((sum, e) => sum + e.magnitude, 0);
  if (total <= 0) return [];

  return usable
    .map((e) => ({
      feature: e.feature,
      magnitude: e.magnitude,
      share: (e.magnitude / total) * 100,
    }))
    .sort((a, b) => b.share - a.share)
    .slice(0, 8);
}

export function AttributionChart({ incident }: { incident: Incident }) {
  const rows = useMemo(() => buildRows(incident), [incident]);
  const summary = incident.explanation_summary;

  return (
    <div className="flex flex-col gap-4">
      {/* Provenance — every field is rendered only if the payload carries it. */}
      <dl className="grid grid-cols-2 gap-x-4 gap-y-3 sm:grid-cols-4">
        <div>
          <dt className="text-[11px] text-content-dim">Anomaly score</dt>
          <dd className="mt-0.5">
            <Mono className="text-[13px] text-content">{num(incident.anomaly_score, 3)}</Mono>
          </dd>
        </div>
        <div>
          <dt className="text-[11px] text-content-dim">Threat score</dt>
          <dd className="mt-0.5">
            <Mono className="text-[13px] text-content">{num(incident.threat_score, 1)}</Mono>
            <span className="text-[12px] text-content-dim"> / 100</span>
          </dd>
        </div>
        <div>
          <dt className="text-[11px] text-content-dim">Priority</dt>
          <dd className="mt-0.5">
            <Mono className="text-[13px] text-content">P{incident.priority}</Mono>
          </dd>
        </div>
        <div>
          <dt className="text-[11px] text-content-dim">Model version</dt>
          <dd className="mt-0.5">
            {incident.model_version ? (
              <Mono className="text-[13px] text-content">{incident.model_version}</Mono>
            ) : (
              <span className="text-[12px] text-content-dim">Not recorded</span>
            )}
          </dd>
        </div>
      </dl>

      {/* Structured summary, when the engine produced one. */}
      {summary?.primary_cause ? (
        <div className="rounded-control border border-line bg-surface-overlay p-3">
          <h3 className="text-[12px] font-semibold text-content">Reported cause</h3>
          <p className="mt-1 text-[13px] text-content-muted">{summary.primary_cause}</p>
          {summary.secondary_cause ? (
            <p className="mt-1.5 text-[12px] text-content-dim">
              Secondary: {summary.secondary_cause}
            </p>
          ) : null}
          {summary.supporting_indicators?.length ? (
            <ul className="mt-2 flex flex-wrap gap-1.5">
              {summary.supporting_indicators
                .filter((s) => s.trim() !== "")
                .map((indicator) => (
                  <li key={indicator}>
                    <Chip>{indicator}</Chip>
                  </li>
                ))}
            </ul>
          ) : null}
        </div>
      ) : null}

      {/* Attribution */}
      <section>
        <h3 className="text-[12px] font-semibold text-content">Feature contributions</h3>
        {rows.length === 0 ? (
          <div className="mt-1 rounded-control border border-line bg-surface-overlay">
            <UnavailableState
              compact
              title="No attribution recorded"
              detail="This incident was stored without per-feature contributions, so none can be shown."
            />
          </div>
        ) : (
          <>
            <p className="mt-0.5 text-[12px] text-content-dim">
              Relative contribution as recorded on this incident. Shares are normalised across the
              {rows.length === 1 ? " single value" : ` ${rows.length} values`} stored.
            </p>

            <div className="mt-3 h-[max(160px,calc(1.75rem*var(--rows)))]" style={{ ["--rows" as string]: rows.length }}>
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={rows} layout="vertical" margin={{ top: 0, right: 44, bottom: 0, left: 0 }}>
                  <XAxis type="number" domain={[0, 100]} hide />
                  <YAxis
                    type="category"
                    dataKey="feature"
                    width={150}
                    tickLine={false}
                    axisLine={false}
                    tick={{ fill: "#9aa4b0", fontSize: 12 }}
                    tickFormatter={(v: string) => humanizeEnum(v)}
                  />
                  <Bar dataKey="share" radius={[0, 2, 2, 0]} barSize={12} isAnimationActive={false}>
                    {rows.map((row, index) => (
                      <Cell key={row.feature} fill={index === 0 ? "#4fa8c5" : "#2d6a80"} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>

            {/* The numbers, because a chart alone is not an audit record. */}
            <ul className="mt-2 flex flex-col gap-1">
              {rows.map((row) => (
                <li
                  key={row.feature}
                  className="flex items-baseline justify-between gap-3 text-[12px]"
                >
                  <span className="truncate text-content-muted">{humanizeEnum(row.feature)}</span>
                  <Mono className="shrink-0 text-content">{row.share.toFixed(1)}%</Mono>
                </li>
              ))}
            </ul>
          </>
        )}
      </section>
    </div>
  );
}
