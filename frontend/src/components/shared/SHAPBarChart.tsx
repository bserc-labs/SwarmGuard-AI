import { Bar, BarChart, CartesianGrid, LabelList, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

interface SHAPBarChartProps {
  values: Array<{ feature: string; value: number }> | null | undefined;
}

interface SHAPChartDatum {
  feature: string;
  value: number;
  percentage: number;
}

export function SHAPBarChart({ values }: SHAPBarChartProps) {
  const chartData = (() => {
    const safeValues = values ?? [];
    if (safeValues.length === 0) return [];

    const total = safeValues.reduce((sum, item) => sum + Math.abs(item.value), 0);

    return safeValues
      .map((item) => ({
        feature: item.feature,
        value: item.value,
        percentage: total > 0 ? (Math.abs(item.value) / total) * 100 : 0,
      }))
      .sort((a, b) => b.value - a.value);
  })();

  if (chartData.length === 0) {
    return (
      <div className="flex min-h-[160px] items-center justify-center rounded-md border border-white/10 bg-sg-surface-dim/50 px-4 text-center">
        <p className="text-sm text-sg-text-muted font-mono">No explainability data available.</p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="space-y-1">
        <h3 className="text-sm font-semibold text-sg-text">AI Threat Explainability (SHAP)</h3>
        <p className="text-xs text-sg-text-muted font-mono leading-relaxed">
          Shows the contribution of telemetry features responsible for the current AI threat prediction.
        </p>
      </div>

      <div className="h-[220px] w-full">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={chartData} margin={{ top: 8, right: 8, left: -16, bottom: 4 }}>
            <CartesianGrid stroke="rgba(255,255,255,0.06)" vertical={false} />
            <XAxis dataKey="feature" stroke="#859398" fontSize={11} tickLine={false} axisLine={false} />
            <YAxis stroke="#859398" fontSize={11} tickLine={false} axisLine={false} />
            <Tooltip
              cursor={{ fill: "rgba(255,255,255,0.04)" }}
              contentStyle={{
                backgroundColor: "rgba(14,20,23,0.92)",
                border: "1px solid rgba(255,255,255,0.1)",
                borderRadius: "8px",
                color: "#dde4e6",
              }}
              labelFormatter={(label) => `Feature: ${label}`}
              content={({ active, payload, label }) => {
                if (!active || !payload?.length) return null;

                const datum = payload[0].payload as SHAPChartDatum;
                return (
                  <div className="rounded-lg border border-white/10 bg-sg-surface-dim/95 px-3 py-2 text-xs shadow-lg">
                    <p className="font-semibold text-sg-text">{label}</p>
                    <p className="mt-1 text-sg-text-muted">SHAP value: {datum.value.toFixed(3)}</p>
                    <p className="text-sg-text-muted">Percentage contribution: {datum.percentage.toFixed(1)}%</p>
                  </div>
                );
              }}
            />
            <Bar
              dataKey="value"
              radius={[4, 4, 0, 0]}
              fill="#00d9ff"
              animationBegin={0}
              animationDuration={700}
              animationEasing="ease-out"
            >
              <LabelList
                dataKey="percentage"
                position="top"
                offset={6}
                formatter={(value: number) => `${value.toFixed(0)}%`}
                className="fill-sg-text-muted"
                style={{ fontSize: 10 }}
              />
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
