export type Screen = {
  slug: string;
  title: string;
  description: string;
  category: string;
};

export const screens: Screen[] = [
  {
    slug: "secure_login",
    title: "Secure Login",
    description: "Terminal authentication portal.",
    category: "Access",
  },
  {
    slug: "dashboard_with_logout_modal_overlay",
    title: "Command Dashboard",
    description: "Main dashboard with logout modal overlay.",
    category: "Command",
  },
  {
    slug: "unified_sidebar_with_access_tags",
    title: "Unified Sidebar",
    description: "Navigation sidebar with role-based access tags.",
    category: "Command",
  },
  {
    slug: "live_telemetry_monitoring",
    title: "Live Telemetry",
    description: "Real-time telemetry monitoring stream.",
    category: "Monitoring",
  },
  {
    slug: "drone_fleet_monitoring",
    title: "Drone Fleet Monitoring",
    description: "Fleet status, positions, and health.",
    category: "Monitoring",
  },
  {
    slug: "threat_intelligence_hub",
    title: "Threat Intelligence Hub",
    description: "Aggregated threat intel dashboard.",
    category: "Intelligence",
  },
  {
    slug: "active_incidents_list",
    title: "Active Incidents",
    description: "List of open and escalated incidents.",
    category: "Incidents",
  },
  {
    slug: "incident_deep_analysis",
    title: "Incident Deep Analysis",
    description: "Full forensic breakdown of an incident.",
    category: "Incidents",
  },
  {
    slug: "incident_deep_analysis_unified_actions_with_access_tags",
    title: "Incident Analysis · Unified Actions",
    description: "Deep analysis with unified action panel.",
    category: "Incidents",
  },
  {
    slug: "drone_management_admin_terminal",
    title: "Drone Management Terminal",
    description: "Admin terminal for drone fleet control.",
    category: "Administration",
  },
  {
    slug: "user_profile",
    title: "User Profile",
    description: "Operator profile & activity.",
    category: "Account",
  },
  {
    slug: "system_settings_account_security_terminal",
    title: "System Settings",
    description: "Account security & system preferences.",
    category: "Account",
  },
  {
    slug: "signal_lost_404",
    title: "Signal Lost · 404",
    description: "Not found / lost signal page.",
    category: "System",
  },
];

export function findScreen(slug: string): Screen | undefined {
  return screens.find((s) => s.slug === slug);
}
