/**
 * Inline SVG icon set.
 *
 * Replaces the Material Symbols webfont, which was loaded from a Google CDN.
 * A defense console should not depend on a third-party network request to
 * render its navigation, and the font added ~100KB before first paint.
 *
 * All paths are 24x24, stroke-based, and inherit currentColor.
 */

import type { SVGProps } from "react";

export type IconName =
  | "dashboard"
  | "activity"
  | "drone"
  | "shield"
  | "alert"
  | "settings"
  | "user"
  | "logout"
  | "search"
  | "bell"
  | "close"
  | "menu"
  | "chevron-left"
  | "chevron-right"
  | "chevron-down"
  | "check"
  | "clock"
  | "map-pin"
  | "battery"
  | "signal"
  | "satellite"
  | "gauge"
  | "play"
  | "pause"
  | "refresh"
  | "download"
  | "plus"
  | "trash"
  | "info"
  | "external"
  | "lock"
  | "eye-off"
  | "eye"
  | "filter"
  | "arrow-left"
  | "arrow-up-right"
  | "zap";

const PATHS: Record<IconName, string> = {
  dashboard: "M4 4h7v7H4zM13 4h7v4h-7zM13 10h7v10h-7zM4 13h7v7H4z",
  activity: "M3 12h4l3 8 4-16 3 8h4",
  drone: "M12 9.5h0M7 7l3 3M17 7l-3 3M7 17l3-3M17 17l-3-3M5 5a2 2 0 100 0M19 5a2 2 0 100 0M5 19a2 2 0 100 0M19 19a2 2 0 100 0M9.5 9.5h5v5h-5z",
  shield: "M12 3l7 3v5c0 4.5-3 8.3-7 10-4-1.7-7-5.5-7-10V6z",
  alert: "M12 4l9 16H3zM12 10v4M12 17.5h0",
  settings:
    "M12 15a3 3 0 100-6 3 3 0 000 6zM19.4 15a1.6 1.6 0 00.3 1.8l.1.1a2 2 0 11-2.8 2.8l-.1-.1a1.6 1.6 0 00-2.7 1.1v.2a2 2 0 11-4 0v-.1a1.6 1.6 0 00-2.7-1.2l-.1.1a2 2 0 11-2.8-2.8l.1-.1A1.6 1.6 0 004.6 15a2 2 0 11.1-4h.1a1.6 1.6 0 001.2-2.7l-.1-.1a2 2 0 112.8-2.8l.1.1a1.6 1.6 0 002.7-1.2V4a2 2 0 114 0v.1A1.6 1.6 0 0019 5.4l.1-.1a2 2 0 112.8 2.8l-.1.1a1.6 1.6 0 001.1 2.7h.1",
  user: "M20 21v-2a4 4 0 00-4-4H8a4 4 0 00-4 4v2M12 11a4 4 0 100-8 4 4 0 000 8z",
  logout: "M9 21H5a2 2 0 01-2-2V5a2 2 0 012-2h4M16 17l5-5-5-5M21 12H9",
  search: "M11 19a8 8 0 100-16 8 8 0 000 16zM21 21l-4.3-4.3",
  bell: "M18 8a6 6 0 10-12 0c0 7-3 9-3 9h18s-3-2-3-9M13.7 21a2 2 0 01-3.4 0",
  close: "M18 6L6 18M6 6l12 12",
  menu: "M3 12h18M3 6h18M3 18h18",
  "chevron-left": "M15 18l-6-6 6-6",
  "chevron-right": "M9 18l6-6-6-6",
  "chevron-down": "M6 9l6 6 6-6",
  check: "M20 6L9 17l-5-5",
  clock: "M12 21a9 9 0 100-18 9 9 0 000 18zM12 7v5l3 2",
  "map-pin": "M20 10c0 6-8 12-8 12s-8-6-8-12a8 8 0 1116 0zM12 13a3 3 0 100-6 3 3 0 000 6z",
  battery: "M3 8h14v8H3zM20 11v2",
  signal: "M2 20h.01M7 20v-4M12 20v-8M17 20V8M22 20V4",
  satellite:
    "M13 7l4 4M11 5l3-3 6 6-3 3M5 11l-3 3 6 6 3-3M9 9l6 6M18 15a4 4 0 01-4 4M21 15a7 7 0 01-7 7",
  gauge: "M12 21a9 9 0 100-18 9 9 0 000 18zM12 12l4-4",
  play: "M6 4l14 8-14 8z",
  pause: "M8 5v14M16 5v14",
  refresh: "M21 12a9 9 0 11-3-6.7M21 4v5h-5",
  download: "M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4M7 10l5 5 5-5M12 15V3",
  plus: "M12 5v14M5 12h14",
  trash: "M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6M10 11v6M14 11v6",
  info: "M12 21a9 9 0 100-18 9 9 0 000 18zM12 16v-4M12 8h0",
  external: "M18 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2V8a2 2 0 012-2h6M15 3h6v6M10 14L21 3",
  lock: "M5 11h14v10H5zM8 11V7a4 4 0 118 0v4",
  "eye-off":
    "M17.9 17.9A10.1 10.1 0 0112 20c-7 0-11-8-11-8a18.5 18.5 0 015.1-6M9.9 4.2A9.1 9.1 0 0112 4c7 0 11 8 11 8a18.5 18.5 0 01-2.2 3.2M1 1l22 22M9.9 9.9a3 3 0 104.2 4.2",
  eye: "M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8zM12 15a3 3 0 100-6 3 3 0 000 6z",
  filter: "M22 3H2l8 9.5V19l4 2v-8.5z",
  "arrow-left": "M19 12H5M12 19l-7-7 7-7",
  "arrow-up-right": "M7 17L17 7M7 7h10v10",
  zap: "M13 2L3 14h9l-1 8 10-12h-9z",
};

export interface IconProps extends Omit<SVGProps<SVGSVGElement>, "name"> {
  name: IconName;
  size?: number;
  /**
   * Accessible label. Omit for icons that sit beside visible text — those are
   * decorative and are hidden from assistive technology.
   */
  title?: string;
}

export function Icon({ name, size = 16, title, className, ...rest }: IconProps) {
  const decorative = !title;
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.75}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden={decorative || undefined}
      role={decorative ? undefined : "img"}
      focusable="false"
      {...rest}
    >
      {title ? <title>{title}</title> : null}
      <path d={PATHS[name]} />
    </svg>
  );
}
