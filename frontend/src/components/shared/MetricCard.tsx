import { GlassCard } from "./GlassCard";

interface MetricCardProps {
  icon: string;
  label: string;
  value: string | number;
  trend?: string;
  trendUp?: boolean;
  glowColor?: string;
  loading?: boolean;
}

export function MetricCard({ icon, label, value, trend, trendUp, glowColor, loading }: MetricCardProps) {
  if (loading) {
    return (
      <GlassCard>
        <div className="skeleton h-4 w-20 mb-3" />
        <div className="skeleton h-8 w-16 mb-2" />
        <div className="skeleton h-3 w-24" />
      </GlassCard>
    );
  }

  return (
    <GlassCard className="group hover:border-sg-primary/30 transition-all duration-300">
      <div className="flex items-center justify-between mb-3">
        <span className="text-xs uppercase tracking-widest text-sg-text-muted font-semibold">{label}</span>
        <span
          className="material-symbols-outlined text-xl"
          style={{ color: glowColor || "var(--color-sg-primary)" }}
        >
          {icon}
        </span>
      </div>
      <div className="text-3xl font-bold tracking-tight text-sg-text mb-1">{value}</div>
      {trend && (
        <div className={`text-xs font-medium ${trendUp ? "text-emerald-400" : "text-red-400"}`}>
          {trendUp ? "↑" : "↓"} {trend}
        </div>
      )}
    </GlassCard>
  );
}
