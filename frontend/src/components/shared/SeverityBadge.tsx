import { SEVERITY_COLORS } from "@/lib/constants";

interface SeverityBadgeProps {
  severity: string;
  size?: "sm" | "md";
}

export function SeverityBadge({ severity, size = "sm" }: SeverityBadgeProps) {
  const colors = SEVERITY_COLORS[severity] || SEVERITY_COLORS.LOW;
  const sizeClasses = size === "sm" ? "text-[10px] px-2 py-0.5" : "text-xs px-3 py-1";

  return (
    <span
      className={`inline-flex items-center font-bold uppercase tracking-wider rounded-full border ${colors.bg} ${colors.text} ${colors.border} ${sizeClasses}`}
    >
      {severity === "CRITICAL" && <span className="w-1.5 h-1.5 bg-red-400 rounded-full mr-1.5 animate-pulse-red" />}
      {severity}
    </span>
  );
}
