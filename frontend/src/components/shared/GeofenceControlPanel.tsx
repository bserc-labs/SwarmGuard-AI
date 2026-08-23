/**
 * Geofence zone management.
 *
 * Create and deactivate restricted zones. Both actions are gated on
 * geofence.manage; without it the panel is read-only rather than hidden, so an
 * analyst can still see which zones are in force.
 *
 * Operational note surfaced to the user: zones are stored and drawn, but the
 * backend has no breach-detection service wired to the ingest path. The map
 * computes containment client-side for display only, and this panel says so
 * rather than implying enforcement.
 */

import { useMemo, useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { api, ApiError, type GeofenceZone } from "@/services/api";
import { DataState } from "@/components/ui/DataState";
import { Icon } from "@/components/ui/Icon";
import { Button, Chip, Field, Input, Mono, Panel, PanelBody, PanelHeader, Select } from "@/components/ui/primitives";
import { parseVertices } from "@/lib/geofence";
import { hasPermission, Permissions } from "@/lib/rbac";
import { useAuth } from "@/hooks/useAuth";

type ZoneKind = "CIRCLE" | "POLYGON";


export function GeofenceControlPanel() {
  const queryClient = useQueryClient();
  const { user, role } = useAuth();
  const canManage = hasPermission(user?.role ?? role, Permissions.GEOFENCE_MANAGE);

  const [showForm, setShowForm] = useState(false);
  const [name, setName] = useState("");
  const [kind, setKind] = useState<ZoneKind>("CIRCLE");
  const [severity, setSeverity] = useState("CRITICAL");
  const [lat, setLat] = useState("");
  const [lng, setLng] = useState("");
  const [radius, setRadius] = useState("500");
  const [vertices, setVertices] = useState("");
  const [formError, setFormError] = useState<string | null>(null);

  const { points: parsedVertices, error: vertexError } = useMemo(
    () => parseVertices(vertices),
    [vertices],
  );

  const zonesQuery = useQuery({
    queryKey: ["geofences"],
    queryFn: () => api.getGeofences(),
  });

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["geofences"] });

  const createZone = useMutation({
    mutationFn: api.createGeofence,
    onSuccess: (zone) => {
      toast.success(`Zone “${zone.name}” created`);
      resetForm();
      invalidate();
    },
    onError: (error: unknown) => {
      const message =
        error instanceof ApiError && error.status === 400
          ? "Could not create the zone. The name may already be in use."
          : error instanceof Error
            ? error.message
            : "Could not create the zone.";
      setFormError(message);
    },
  });

  const removeZone = useMutation({
    mutationFn: (zoneId: number) => api.deleteGeofence(zoneId),
    onSuccess: () => {
      toast.success("Zone deactivated");
      invalidate();
    },
    onError: () => toast.error("Could not deactivate the zone."),
  });

  function resetForm() {
    setShowForm(false);
    setName("");
    setLat("");
    setLng("");
    setRadius("500");
    setVertices("");
    setFormError(null);
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setFormError(null);

    if (!name.trim()) return setFormError("Give the zone a name.");

    if (kind === "CIRCLE") {
      const latNum = Number(lat);
      const lngNum = Number(lng);
      const radiusNum = Number(radius);

      if (!Number.isFinite(latNum) || Math.abs(latNum) > 90)
        return setFormError("Latitude must be between −90 and 90.");
      if (!Number.isFinite(lngNum) || Math.abs(lngNum) > 180)
        return setFormError("Longitude must be between −180 and 180.");
      if (!Number.isFinite(radiusNum) || radiusNum <= 0)
        return setFormError("Radius must be greater than zero.");

      createZone.mutate({
        name: name.trim(),
        zone_type: "CIRCLE",
        severity,
        coordinates: { center: [latNum, lngNum], radius: radiusNum },
      });
      return;
    }

    if (vertexError) return setFormError(vertexError);
    if (parsedVertices.length < 3)
      return setFormError("A polygon needs at least three vertices.");

    createZone.mutate({
      name: name.trim(),
      zone_type: "POLYGON",
      severity,
      coordinates: parsedVertices,
    });
  }

  return (
    <Panel>
      <PanelHeader
        title="Restricted zones"
        description="Drawn on the fleet map. Containment is evaluated in the browser for display; no server-side breach alerting is configured."
        actions={
          canManage ? (
            <Button
              size="sm"
              variant={showForm ? "ghost" : "primary"}
              icon={showForm ? "close" : "plus"}
              onClick={() => (showForm ? resetForm() : setShowForm(true))}
            >
              {showForm ? "Cancel" : "Add zone"}
            </Button>
          ) : undefined
        }
      />

      {showForm && canManage ? (
        <form onSubmit={handleSubmit} className="border-b border-line-subtle bg-surface-overlay p-4">
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Name" htmlFor="zone-name">
              <Input
                id="zone-name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="North perimeter"
                autoComplete="off"
              />
            </Field>

            <Field label="Severity" htmlFor="zone-severity">
              <Select
                id="zone-severity"
                value={severity}
                onChange={(e) => setSeverity(e.target.value)}
              >
                <option value="CRITICAL">Critical</option>
                <option value="WARNING">Warning</option>
              </Select>
            </Field>

            <Field label="Shape" htmlFor="zone-kind">
              <Select
                id="zone-kind"
                value={kind}
                onChange={(e) => setKind(e.target.value as ZoneKind)}
              >
                <option value="CIRCLE">Circle</option>
                <option value="POLYGON">Polygon</option>
              </Select>
            </Field>

            {kind === "CIRCLE" ? (
              <>
                <Field label="Radius" htmlFor="zone-radius" hint="Metres">
                  <Input
                    id="zone-radius"
                    type="number"
                    min={1}
                    value={radius}
                    onChange={(e) => setRadius(e.target.value)}
                  />
                </Field>

                <Field label="Centre latitude" htmlFor="zone-lat">
                  <Input
                    id="zone-lat"
                    type="number"
                    step="any"
                    value={lat}
                    onChange={(e) => setLat(e.target.value)}
                    placeholder="34.05220"
                  />
                </Field>

                <Field label="Centre longitude" htmlFor="zone-lng">
                  <Input
                    id="zone-lng"
                    type="number"
                    step="any"
                    value={lng}
                    onChange={(e) => setLng(e.target.value)}
                    placeholder="-118.24370"
                  />
                </Field>
              </>
            ) : (
              <div className="sm:col-span-2">
                <Field
                  label="Vertices"
                  htmlFor="zone-vertices"
                  hint="One lat, lng pair per line. At least three, in order around the perimeter."
                  error={vertexError ?? undefined}
                >
                  <textarea
                    id="zone-vertices"
                    value={vertices}
                    onChange={(e) => setVertices(e.target.value)}
                    rows={5}
                    spellCheck={false}
                    placeholder={"34.0530, -118.2450\n34.0530, -118.2400\n34.0490, -118.2400\n34.0490, -118.2450"}
                    className="w-full rounded-control border border-line-strong bg-surface-sunken px-2.5 py-2 font-mono text-[12px] text-content transition-colors placeholder:text-content-dim focus:border-accent focus:outline-none focus-visible:outline-2 focus-visible:outline-accent-bright focus-visible:outline-offset-1"
                  />
                </Field>
                {parsedVertices.length >= 3 ? (
                  <p className="mt-1 text-[11px] text-content-dim">
                    {parsedVertices.length} vertices parsed. The polygon closes automatically.
                  </p>
                ) : null}
              </div>
            )}
          </div>

          {formError ? (
            <p role="alert" className="mt-3 text-[12px] text-critical">
              {formError}
            </p>
          ) : null}

          <div className="mt-3 flex gap-2">
            <Button type="submit" variant="primary" size="sm" loading={createZone.isPending}>
              Create zone
            </Button>
            <Button type="button" variant="ghost" size="sm" onClick={resetForm}>
              Cancel
            </Button>
          </div>
        </form>
      ) : null}

      <DataState
        isLoading={zonesQuery.isLoading}
        isError={zonesQuery.isError}
        error={zonesQuery.error}
        data={zonesQuery.data}
        onRetry={() => zonesQuery.refetch()}
        compact
        empty={
          <PanelBody>
            <p className="text-center text-[12px] text-content-dim">
              No restricted zones defined.
            </p>
          </PanelBody>
        }
      >
        {(zones) => {
          const active = zones.filter((z) => z.is_active);
          if (active.length === 0) {
            return (
              <PanelBody>
                <p className="text-center text-[12px] text-content-dim">
                  All zones are deactivated.
                </p>
              </PanelBody>
            );
          }
          return (
            <ul className="divide-y divide-line-subtle">
              {active.map((zone: GeofenceZone) => (
                <li key={zone.id} className="flex items-center gap-3 px-4 py-2.5">
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-[13px] text-content">{zone.name}</p>
                    <p className="mt-0.5 flex items-center gap-1.5">
                      <Chip tone={zone.severity?.toUpperCase() === "CRITICAL" ? "critical" : "warning"}>
                        {zone.severity?.toLowerCase() ?? "unspecified"}
                      </Chip>
                      <Mono className="text-content-dim">{zone.zone_type?.toLowerCase()}</Mono>
                    </p>
                  </div>
                  {canManage ? (
                    <button
                      type="button"
                      onClick={() => removeZone.mutate(zone.id)}
                      disabled={removeZone.isPending}
                      className="flex h-7 w-7 shrink-0 items-center justify-center rounded-control text-content-dim transition-colors hover:bg-surface-hover hover:text-critical disabled:opacity-50"
                    >
                      <Icon name="trash" size={14} title={`Deactivate ${zone.name}`} />
                    </button>
                  ) : null}
                </li>
              ))}
            </ul>
          );
        }}
      </DataState>
    </Panel>
  );
}
