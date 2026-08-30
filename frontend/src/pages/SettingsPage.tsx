/**
 * Organization settings.
 *
 * These values are stored per organization by the backend. The two severity
 * thresholds are now read by the detection path — they were previously
 * persisted and ignored — so the copy below describes what they actually do,
 * including the one case where they do not apply.
 */

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { api, type SystemSettings } from "@/services/api";
import { ErrorState, LoadingState, PermissionDeniedState } from "@/components/ui/DataState";
import { Icon } from "@/components/ui/Icon";
import {
  Button,
  Field,
  Input,
  PageHeader,
  Panel,
  PanelBody,
  PanelHeader,
  Select,
} from "@/components/ui/primitives";
import { hasPermission, Permissions } from "@/lib/rbac";
import { useAuth } from "@/hooks/useAuth";

function Toggle({
  id,
  label,
  description,
  checked,
  disabled,
  onChange,
}: {
  id: string;
  label: string;
  description: string;
  checked: boolean;
  disabled: boolean;
  onChange: (value: boolean) => void;
}) {
  return (
    <div className="flex items-start justify-between gap-4 border-b border-line-subtle py-3 last:border-b-0">
      <div className="min-w-0">
        <label htmlFor={id} className="text-[13px] font-medium text-content">
          {label}
        </label>
        <p className="mt-0.5 text-[12px] leading-snug text-content-muted">{description}</p>
      </div>
      <button
        id={id}
        type="button"
        role="switch"
        aria-checked={checked}
        disabled={disabled}
        onClick={() => onChange(!checked)}
        className={`relative mt-0.5 h-5 w-9 shrink-0 rounded-full border transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${
          checked ? "border-accent bg-accent-dim" : "border-line-strong bg-surface-overlay"
        }`}
      >
        <span
          aria-hidden="true"
          className={`absolute top-0.5 h-3.5 w-3.5 rounded-full transition-all ${
            checked ? "left-[18px] bg-accent-bright" : "left-0.5 bg-content-dim"
          }`}
        />
      </button>
    </div>
  );
}

export default function SettingsPage() {
  const queryClient = useQueryClient();
  const { user, role } = useAuth();
  const effectiveRole = user?.role ?? role;

  const canRead = hasPermission(effectiveRole, Permissions.SETTINGS_READ);
  const canManage = hasPermission(effectiveRole, Permissions.SETTINGS_MANAGE);

  // Null means "unedited". The effective value is derived from the server copy
  // rather than mirrored into state by an effect, so a background refetch cannot
  // race the operator's edits.
  const [edits, setEdits] = useState<SystemSettings | null>(null);

  const settingsQuery = useQuery({
    queryKey: ["settings"],
    queryFn: () => api.getSettings(),
    enabled: canRead,
  });

  const draft = edits ?? settingsQuery.data ?? null;

  const save = useMutation({
    mutationFn: (payload: Partial<SystemSettings>) => api.updateSettings(payload),
    onSuccess: () => {
      toast.success("Settings saved");
      setEdits(null); // fall back to the freshly refetched server copy
      queryClient.invalidateQueries({ queryKey: ["settings"] });
    },
    onError: (error: unknown) =>
      toast.error(error instanceof Error ? error.message : "Could not save settings."),
  });

  if (!canRead) {
    return (
      <>
        <PageHeader title="Settings" />
        <Panel>
          <PermissionDeniedState />
        </Panel>
      </>
    );
  }

  if (settingsQuery.isLoading || draft === null) {
    return (
      <>
        <PageHeader title="Settings" />
        <Panel>
          {settingsQuery.isError ? (
            <ErrorState error={settingsQuery.error} onRetry={() => settingsQuery.refetch()} />
          ) : (
            <LoadingState rows={6} />
          )}
        </Panel>
      </>
    );
  }

  const dirty =
    edits !== null &&
    settingsQuery.data !== undefined &&
    JSON.stringify(edits) !== JSON.stringify(settingsQuery.data);

  /**
   * The same rule the backend enforces, checked here so the operator is not
   * offered a Save that will come back 422. The server remains the authority —
   * this only avoids a pointless round trip.
   */
  const bandsValid =
    draft.high_threshold > 0 &&
    draft.critical_threshold <= 1 &&
    draft.high_threshold < draft.critical_threshold;

  const update = <K extends keyof SystemSettings>(key: K, value: SystemSettings[K]) =>
    setEdits({ ...draft, [key]: value });

  return (
    <>
      <PageHeader
        title="Settings"
        description="Applies to your organization only."
        actions={
          canManage ? (
            <div className="flex gap-2">
              <Button
                size="sm"
                variant="ghost"
                disabled={!dirty || save.isPending}
                onClick={() => setEdits(null)}
              >
                Discard
              </Button>
              <Button
                size="sm"
                variant="primary"
                disabled={!dirty || !bandsValid || save.isPending}
                loading={save.isPending}
                onClick={() => save.mutate(draft)}
              >
                Save changes
              </Button>
            </div>
          ) : undefined
        }
      />

      {!canManage ? (
        <p className="mb-4 flex items-start gap-2 rounded-control border border-line bg-surface-overlay px-3 py-2 text-[12px] text-content-muted">
          <Icon name="lock" size={13} className="mt-0.5 shrink-0 text-content-dim" />
          <span>You can view these settings but not change them.</span>
        </p>
      ) : null}

      <div className="grid gap-4 lg:grid-cols-2">
        <Panel>
          <PanelHeader
            title="Severity thresholds"
            description="Stored per organization."
          />
          <PanelBody className="flex flex-col gap-4">
            <Field
              label="Critical threshold"
              htmlFor="critical-threshold"
              hint="Score at or above which an incident is treated as critical."
            >
              <Input
                id="critical-threshold"
                type="number"
                min={0}
                max={1}
                step={0.01}
                value={draft.critical_threshold}
                disabled={!canManage}
                onChange={(e) => update("critical_threshold", Number(e.target.value))}
              />
            </Field>

            <Field
              label="High threshold"
              htmlFor="high-threshold"
              hint="Score at or above which an incident is treated as high."
            >
              <Input
                id="high-threshold"
                type="number"
                min={0}
                max={1}
                step={0.01}
                value={draft.high_threshold}
                disabled={!canManage}
                onChange={(e) => update("high_threshold", Number(e.target.value))}
              />
            </Field>

            {draft.high_threshold >= draft.critical_threshold ? (
              <p role="alert" className="text-[12px] text-warning">
                The high threshold must be below the critical threshold, otherwise no incident can
                fall into the high band. The server will reject this.
              </p>
            ) : null}

            <p className="flex items-start gap-2 rounded-control border border-line bg-surface-overlay px-2.5 py-2 text-[11px] leading-relaxed text-content-muted">
              <Icon name="info" size={13} className="mt-0.5 shrink-0 text-content-dim" />
              <span>
                These bands apply to <strong>new</strong> detections for this organization.
                Incidents already recorded keep the severity they were given, so changing a
                threshold never rewrites history. A detector that determines its own severity — a
                physical-plausibility violation, or a breach of a zone you marked critical — sets a
                floor these thresholds can raise but not lower.
              </span>
            </p>
          </PanelBody>
        </Panel>

        <Panel>
          <PanelHeader title="Console and notifications" />
          <PanelBody>
            <Field label="Refresh rate" htmlFor="refresh-rate" hint="Stored preference for polling cadence.">
              <Select
                id="refresh-rate"
                value={draft.refresh_rate}
                disabled={!canManage}
                onChange={(e) => update("refresh_rate", e.target.value)}
              >
                <option value="1s">1 second</option>
                <option value="5s">5 seconds</option>
                <option value="10s">10 seconds</option>
                <option value="30s">30 seconds</option>
              </Select>
            </Field>

            <div className="mt-4">
              <Toggle
                id="ui-sound"
                label="Alert sound"
                description="Play a sound when a critical alert arrives."
                checked={draft.ui_sound}
                disabled={!canManage}
                onChange={(v) => update("ui_sound", v)}
              />
              <Toggle
                id="push-notif"
                label="Browser notifications"
                description="Show a system notification for critical alerts."
                checked={draft.push_notif}
                disabled={!canManage}
                onChange={(v) => update("push_notif", v)}
              />
              <Toggle
                id="webhooks"
                label="Outbound webhooks"
                description="Forward incidents to a configured endpoint."
                checked={draft.webhooks}
                disabled={!canManage}
                onChange={(v) => update("webhooks", v)}
              />
            </div>

            <p className="mt-3 flex items-start gap-2 rounded-control border border-line bg-surface-overlay px-2.5 py-2 text-[11px] leading-relaxed text-content-muted">
              <Icon name="info" size={13} className="mt-0.5 shrink-0 text-content-dim" />
              <span>
                These preferences are persisted for your organization. No webhook dispatcher or
                notification service is configured on this backend, so the last two have no effect
                yet.
              </span>
            </p>
          </PanelBody>
        </Panel>
      </div>
    </>
  );
}
