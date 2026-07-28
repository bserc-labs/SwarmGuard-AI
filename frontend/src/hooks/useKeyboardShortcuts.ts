import { useEffect } from 'react';
import { toast } from 'sonner';

interface ShortcutConfig {
  onEmergencyLand?: () => void;
  onReturnToHome?: () => void;
  onSafeMode?: () => void;
  enabled?: boolean;
}

export function useKeyboardShortcuts({ onEmergencyLand, onReturnToHome, onSafeMode, enabled = true }: ShortcutConfig) {
  useEffect(() => {
    if (!enabled) return;

    const handler = (e: KeyboardEvent) => {
      // Don't fire when typing in inputs
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return;
      
      if (e.altKey && e.key === 'e') {
        e.preventDefault();
        onEmergencyLand?.();
        toast.info('⌨️ Shortcut: Emergency Land triggered');
      }
      if (e.altKey && e.key === 'r') {
        e.preventDefault();
        onReturnToHome?.();
        toast.info('⌨️ Shortcut: Return To Home triggered');
      }
      if (e.altKey && e.key === 's') {
        e.preventDefault();
        onSafeMode?.();
        toast.info('⌨️ Shortcut: Safe Mode triggered');
      }
    };

    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [enabled, onEmergencyLand, onReturnToHome, onSafeMode]);
}
