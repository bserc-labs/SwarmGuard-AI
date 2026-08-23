/**
 * Global tactical shortcuts.
 *
 *   Alt+E  Emergency land
 *   Alt+R  Return to home
 *   Alt+S  Switch to safe mode
 *
 * These map to command *requests*, which the backend records as PENDING and
 * which a second authorised user must approve. The shortcut therefore never
 * actuates anything on its own — the confirmation dialog says so explicitly.
 *
 * The hook reports the intent; it does not fire the request itself. Wiring the
 * confirmation is the caller's job so the dialog can live in the app shell.
 */

import { useEffect } from "react";
import type { CommandType } from "@/services/api";

export interface ShortcutIntent {
  command: CommandType;
  label: string;
  /** True for commands that bring an aircraft down. */
  destructive: boolean;
}

export const SHORTCUTS: Record<string, ShortcutIntent> = {
  e: { command: "EMERGENCY_LAND", label: "Emergency land", destructive: true },
  r: { command: "RETURN_TO_HOME", label: "Return to home", destructive: false },
  s: { command: "SWITCH_SAFE_MODE", label: "Switch to safe mode", destructive: false },
};

/** Typing in a field must never trigger a fleet command. */
function isEditableTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  if (target.isContentEditable) return true;
  const tag = target.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT";
}

export function useKeyboardShortcuts({
  onIntent,
  enabled = true,
}: {
  onIntent: (intent: ShortcutIntent) => void;
  enabled?: boolean;
}): void {
  useEffect(() => {
    if (!enabled) return;

    const handler = (event: KeyboardEvent) => {
      // Alt only. Requiring Ctrl/Meta to be absent avoids colliding with
      // browser and OS chords.
      if (!event.altKey || event.ctrlKey || event.metaKey) return;
      if (isEditableTarget(event.target)) return;

      const intent = SHORTCUTS[event.key.toLowerCase()];
      if (!intent) return;

      event.preventDefault();
      onIntent(intent);
    };

    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [enabled, onIntent]);
}
