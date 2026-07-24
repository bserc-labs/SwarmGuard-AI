export const NAV_ITEMS = [
  { label: "Dashboard", icon: "dashboard", path: "/dashboard" },
  { label: "Live Telemetry", icon: "sensors", path: "/telemetry" },
  { label: "Drone Fleet", icon: "screenshot_monitor", path: "/fleet" },
  { label: "Threat Intelligence", icon: "policy", path: "/threats" },
  { label: "Incidents", icon: "warning", path: "/incidents", badge: true },
  { label: "Drone Management", icon: "settings_remote", path: "/admin" },
] as const;

export const NAV_BOTTOM = [
  { label: "Settings", icon: "settings", path: "/settings" },
  { label: "Profile", icon: "account_circle", path: "/profile" },
] as const;

export const SEVERITY_COLORS: Record<string, { bg: string; text: string; border: string }> = {
  CRITICAL: { bg: "bg-red-500/20", text: "text-red-400", border: "border-red-500/30" },
  HIGH: { bg: "bg-amber-500/20", text: "text-amber-400", border: "border-amber-500/30" },
  MEDIUM: { bg: "bg-sg-primary/20", text: "text-sg-primary", border: "border-sg-primary/30" },
  LOW: { bg: "bg-blue-500/20", text: "text-blue-400", border: "border-blue-500/30" },
};

export const STATUS_COLORS: Record<string, { bg: string; text: string }> = {
  NOMINAL: { bg: "bg-emerald-500/20", text: "text-emerald-400" },
  ALERT: { bg: "bg-red-500/20", text: "text-red-400" },
  WARNING: { bg: "bg-amber-500/20", text: "text-amber-400" },
  OFFLINE: { bg: "bg-sg-text-dim/20", text: "text-sg-text-dim" },
};
