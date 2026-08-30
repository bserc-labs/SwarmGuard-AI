/**
 * Wires the global Alt+E / Alt+R / Alt+S shortcuts to the command-request flow.
 *
 * Lives in the app shell so the shortcuts work from any page. Three deliberate
 * constraints:
 *
 *  - Only mounted for roles holding drone.command.request. Others get nothing,
 *    rather than a dialog that ends in a 403.
 *  - A target drone must be chosen. There is no "all aircraft" broadcast — a
 *    keystroke must not be able to address the whole fleet.
 *  - The dialog states that the request needs a second approver, because that
 *    is what the backend does with it.
 */

import { useCallback, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { api, type CommandType } from "@/services/api";
import { POLL_INTERVALS } from "@/config";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { Mono, Select } from "@/components/ui/primitives";
import { useKeyboardShortcuts, type ShortcutIntent } from "@/hooks/useKeyboardShortcuts";
import { hasPermission, Permissions } from "@/lib/rbac";
import { humanizeEnum } from "@/lib/format";
import { useAuth } from "@/hooks/useAuth";

export function TacticalShortcuts() {
  const { user, role } = useAuth();
  const queryClient = useQueryClient();
  const canRequest = hasPermission(user?.role ?? role, Permissions.DRONE_COMMAND_REQUEST);

  const [intent, setIntent] = useState<ShortcutIntent | null>(null);
  const [targetDrone, setTargetDrone] = useState("");

  const dronesQuery = useQuery({
    queryKey: ["drones"],
    queryFn: () => api.getDrones(),
    refetchInterval: POLL_INTERVALS.fleet,
    enabled: canRequest,
  });

  const drones = useMemo(
    () => [...(dronesQuery.data ?? [])].sort((a, b) => a.drone_id.localeCompare(b.drone_id)),
    [dronesQuery.data],
  );

  const onIntent = useCallback(
    (next: ShortcutIntent) => {
      if (drones.length === 0) {
        toast.error("No drones are registered, so there is nothing to command.");
        return;
      }
      setTargetDrone((current) => current || drones[0].drone_id);
      setIntent(next);
    },
    [drones],
  );

  useKeyboardShortcuts({ onIntent, enabled: canRequest });

  const request = useMutation({
    mutationFn: ({ drone, command }: { drone: string; command: CommandType }) =>
      api.requestCommand(drone, command, "Requested via keyboard shortcut"),
    onSuccess: (command) => {
      toast.success(
        `Request #${command.command_id} recorded as ${command.status.toLowerCase()}. ` +
          "It requires approval before it takes effect.",
      );
      setIntent(null);
      queryClient.invalidateQueries({ queryKey: ["commands"] });
    },
    onError: (error: unknown) =>
      toast.error(error instanceof Error ? error.message : "Could not record the request."),
  });

  if (!canRequest || !intent) return null;

  return (
    <ConfirmDialog
      open
      tone={intent.destructive ? "danger" : "default"}
      title={intent.label}
      confirmLabel="Submit request"
      busy={request.isPending}
      onCancel={() => setIntent(null)}
      onConfirm={() => request.mutate({ drone: targetDrone, command: intent.command })}
      description={
        <div className="flex flex-col gap-3">
          <p>
            This records a <Mono>{intent.command}</Mono> request. It does not reach the aircraft
            until a second authorised user approves it, and the backend does not transmit commands
            to hardware.
          </p>

          <div>
            <label
              htmlFor="shortcut-target"
              className="mb-1.5 block text-[12px] font-medium text-content-muted"
            >
              Target drone
            </label>
            <Select
              id="shortcut-target"
              value={targetDrone}
              onChange={(e) => setTargetDrone(e.target.value)}
            >
              {drones.map((drone) => (
                <option key={drone.id} value={drone.drone_id}>
                  {drone.drone_id} — {humanizeEnum(drone.status)}
                </option>
              ))}
            </Select>
          </div>
        </div>
      }
    />
  );
}
