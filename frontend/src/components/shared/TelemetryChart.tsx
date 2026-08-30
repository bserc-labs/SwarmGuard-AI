/**
 * Time-series for one telemetry metric.
 *
 * Renders only points that carry a finite value for the selected metric, so a
 * gap in the data reads as a gap rather than a drop to zero.
 */

import { useMemo } from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { TelemetryRecord } from "@/services/api";
import { EmptyState } from "@/components/ui/DataState";
import { formatTime, num, parseTimestamp } from "@/lib/format";

export type MetricKey = "altitude" | "speed" | "battery" | "satellites";

const METRICS: Record<MetricKey, { label: string; unit: string; color: string; digits: number }> = {
  altitude: { label: "Altitude", unit: "m", color: "#4fa8c5", digits: 1 },
  speed: { label: "Speed", unit: "m/s", color: "#6fc0d9", digits: 1 },
  battery: { label: "Battery", unit: "%", color: "#4d9e6a", digits: 0 },
  satellites: { label: "Satellites", unit: "", color: "#9aa4b0", digits: 0 },
};

interface Point {
  t: number;
  label: string;
  value: number;
}

export function TelemetryChart({
  records,
  metric,
  height = 200,
}: {
  records: TelemetryRecord[];
  metric: MetricKey;
  height?: number;
}) {
  const config = METRICS[metric];

  const points = useMemo<Point[]>(() => {
    return records
      .map((record) => {
        const raw = record[metric];
        if (typeof raw !== "number" || !Number.isFinite(raw)) return null;
        const date = parseTimestamp(record.created_at);
        const t = date ? date.getTime() : null;
        if (t === null) return null;
        return { t, label: formatTime(record.created_at), value: raw };
      })
      .filter((p): p is Point => p !== null)
      .sort((a, b) => a.t - b.t);
  }, [records, metric]);

  if (points.length === 0) {
    return (
      <EmptyState
        compact
        title={`No ${config.label.toLowerCase()} readings`}
        detail="No packet in this range carried a value for this metric."
      />
    );
  }

  return (
    <div style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={points} margin={{ top: 6, right: 8, bottom: 0, left: -18 }}>
          <CartesianGrid stroke="#242a30" strokeDasharray="2 4" vertical={false} />
          <XAxis
            dataKey="label"
            tick={{ fill: "#6c7783", fontSize: 11 }}
            tickLine={false}
            axisLine={{ stroke: "#242a30" }}
            minTickGap={40}
          />
          <YAxis
            tick={{ fill: "#6c7783", fontSize: 11 }}
            tickLine={false}
            axisLine={false}
            width={48}
            domain={metric === "battery" ? [0, 100] : ["auto", "auto"]}
          />
          <Tooltip
            cursor={{ stroke: "#333b43", strokeWidth: 1 }}
            contentStyle={{
              background: "#1c2126",
              border: "1px solid #333b43",
              borderRadius: 5,
              fontSize: 12,
            }}
            labelStyle={{ color: "#9aa4b0" }}
            itemStyle={{ color: "#e4e8ec" }}
            formatter={(value: number) => [
              `${num(value, config.digits)}${config.unit ? ` ${config.unit}` : ""}`,
              config.label,
            ]}
          />
          <Line
            type="monotone"
            dataKey="value"
            stroke={config.color}
            strokeWidth={1.5}
            dot={false}
            activeDot={{ r: 3, strokeWidth: 0 }}
            isAnimationActive={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

export const TELEMETRY_METRICS = METRICS;
