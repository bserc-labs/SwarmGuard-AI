/**
 * Blocking confirmation.
 *
 * Used for actions that reach an aircraft. A toast is not sufficient here — the
 * operator must acknowledge before the request is recorded, and the dialog
 * states plainly that the command still requires a second approver.
 */

import { useEffect, useRef, type ReactNode } from "react";
import { Icon } from "./Icon";
import { Button } from "./primitives";

export interface ConfirmDialogProps {
  open: boolean;
  title: string;
  description: ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  tone?: "default" | "danger";
  busy?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

export function ConfirmDialog({
  open,
  title,
  description,
  confirmLabel = "Confirm",
  cancelLabel = "Cancel",
  tone = "default",
  busy = false,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  const panelRef = useRef<HTMLDivElement>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;

    // Focus lands on Cancel, not Confirm: an operator who triggered this by a
    // mistyped shortcut should not be able to confirm with a stray Enter.
    cancelRef.current?.focus();

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onCancel();
        return;
      }
      if (event.key !== "Tab" || !panelRef.current) return;

      const focusables = panelRef.current.querySelectorAll<HTMLElement>(
        'button:not([disabled]), [href], [tabindex]:not([tabindex="-1"])',
      );
      if (focusables.length === 0) return;
      const first = focusables[0];
      const last = focusables[focusables.length - 1];

      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };

    document.addEventListener("keydown", onKeyDown, true);
    return () => document.removeEventListener("keydown", onKeyDown, true);
  }, [open, onCancel]);

  useEffect(() => {
    if (!open) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previous;
    };
  }, [open]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center p-4">
      <button
        type="button"
        aria-label="Cancel"
        tabIndex={-1}
        onClick={onCancel}
        className="absolute inset-0 bg-surface-sunken/80"
      />
      <div
        ref={panelRef}
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="confirm-title"
        aria-describedby="confirm-description"
        className="sg-enter relative w-full max-w-md rounded-panel border border-line-strong bg-surface-raised p-5 shadow-2xl"
      >
        <div className="flex items-start gap-3">
          <Icon
            name={tone === "danger" ? "alert" : "info"}
            size={18}
            className={`mt-0.5 shrink-0 ${tone === "danger" ? "text-critical" : "text-accent"}`}
          />
          <div className="min-w-0">
            <h2 id="confirm-title" className="text-[15px] font-semibold text-content">
              {title}
            </h2>
            <div id="confirm-description" className="mt-1.5 text-[13px] leading-relaxed text-content-muted">
              {description}
            </div>
          </div>
        </div>

        <div className="mt-5 flex justify-end gap-2">
          <Button ref={cancelRef} size="sm" onClick={onCancel} disabled={busy}>
            {cancelLabel}
          </Button>
          <Button
            size="sm"
            variant={tone === "danger" ? "danger" : "primary"}
            onClick={onConfirm}
            loading={busy}
          >
            {confirmLabel}
          </Button>
        </div>
      </div>
    </div>
  );
}
