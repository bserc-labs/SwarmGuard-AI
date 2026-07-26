import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { GlassCard } from "./GlassCard";

export interface TelemetryChartPoint {
  label: string;
  value: number;
  [key: string]: string | number;
}

interface TelemetryChartProps {
  title: string;
  data: TelemetryChartPoint[];
  dataKey?: string;
  lineColor?: string;
  unit?: string;
}

export function TelemetryChart({
  title,
  data,
  dataKey = "value",
  lineColor = "#00d9ff",
  unit = "",
}: TelemetryChartProps) {
  const hasData = data.some((item) => {
    const numericValue = Number(item[dataKey]);
    return Number.isFinite(numericValue) && numericValue >= 0;
  });

  const latestValue = data.length > 0 ? Number(data[data.length - 1][dataKey] ?? 0) : 0;

  return (
    <GlassCard className="p-4 h-[220px]">
      <div className="flex items-start justify-between mb-3">
        <div>
          <h3 className="text-sm font-semibold uppercase tracking-wider text-sg-text-muted">{title}</h3>
          <p className="text-[11px] text-sg-text-dim font-mono mt-1">{unit ? `Live ${unit}` : "Live telemetry"}</p>
        </div>
        <div className="rounded-full border border-white/10 bg-black/20 px-2 py-1">
          <span className="text-[11px] font-mono text-sg-text">
            {latestValue.toFixed(1)}{unit}
          </span>
        </div>
      </div>

      <div className="h-[140px]">
        {hasData ? (
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={data} margin={{ top: 6, right: 8, left: -20, bottom: 0 }}>
              <CartesianGrid vertical={false} stroke="rgba(255,255,255,0.06)" strokeDasharray="3 3" />
              <XAxis
                dataKey="label"
                tickLine={false}
                axisLine={false}
                stroke="#859398"
                fontSize={11}
                minTickGap={10}
              />
              <YAxis
                tickLine={false}
                axisLine={false}
                stroke="#859398"
                fontSize={11}
                width={36}
              />
              <Tooltip
                cursor={{ stroke: lineColor, strokeWidth: 1, strokeDasharray: "4 4" }}
                contentStyle={{
                  backgroundColor: "rgba(14,20,23,0.95)",
                  border: "1px solid rgba(255,255,255,0.12)",
                  borderRadius: "8px",
                  color: "#dde4e6",
                }}
                formatter={(value: number | string) => [`${Number(value).toFixed(1)}${unit ? ` ${unit}` : ""}`, title]}
                labelFormatter={(label) => `${label}`}
              />
              <Line
                type="monotone"
                dataKey={dataKey}
                stroke={lineColor}
                strokeWidth={2.5}
                dot={{ r: 2.5, fill: lineColor, strokeWidth: 0 }}
                activeDot={{ r: 5 }}
              />
            </LineChart>
          </ResponsiveContainer>
        ) : (
          <div className="flex h-full items-center justify-center text-center text-sm text-sg-text-dim">
            No telemetry available
          </div>
        )}
      </div>
    </GlassCard>
  );
}
