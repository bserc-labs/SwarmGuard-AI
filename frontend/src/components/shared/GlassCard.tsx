import type { ReactNode } from "react";

interface GlassCardProps {
  children: ReactNode;
  className?: string;
  glow?: boolean;
  scanline?: boolean;
  onClick?: () => void;
}

export function GlassCard({ children, className = "", glow = false, scanline = false, onClick }: GlassCardProps) {
  return (
    <div
      onClick={onClick}
      className={`glass-card relative overflow-hidden p-5 ${glow ? "primary-glow" : ""} ${onClick ? "cursor-pointer" : ""} ${className}`}
    >
      {scanline && <div className="animate-scanline" />}
      {children}
    </div>
  );
}
