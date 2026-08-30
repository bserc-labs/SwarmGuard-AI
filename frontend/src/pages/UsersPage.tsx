/**
 * Team administration.
 *
 * The backend has exposed POST and GET /users/ and a user.manage permission
 * since multi-tenancy landed, but no screen called them. The practical
 * consequence was that an organization could never gain a second account, and
 * the two-person command-approval rule on /admin — which requires a different
 * user to approve what you requested — could not be exercised at all.
 *
 * Validation here mirrors backend/schemas.py exactly (username pattern and
 * length, MIN_PASSWORD_LENGTH) so a malformed entry is caught before the round
 * trip rather than coming back as a 422 the operator has to decode.
 */

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { api, type UserInfo } from "@/services/api";
import {
  DataState,
  EmptyState,
  PermissionDeniedState,
} from "@/components/ui/DataState";
import { Icon } from "@/components/ui/Icon";
import {
  Button,
  Chip,
  Field,
  Input,
  Mono,
  PageHeader,
  Panel,
  PanelBody,
  PanelHeader,
  Select,
  Table,
  Td,
  Th,
} from "@/components/ui/primitives";
import { formatDateTime, humanizeEnum, relativeTime } from "@/lib/format";
import { hasPermission, permissionsFor, Permissions } from "@/lib/rbac";
import { useAuth } from "@/hooks/useAuth";

/** Mirrors the UserRole literal in backend/schemas.py. */
const ROLES = ["observer", "operator", "analyst", "commander", "admin"] as const;
type Role = (typeof ROLES)[number];

const ROLE_SUMMARY: Record<Role, string> = {
  observer: "Read-only. Cannot acknowledge, command, or change settings.",
  operator: "Reads telemetry and requests commands. Cannot approve them.",
  analyst: "Works the incident queue: acknowledge, assign, investigate, resolve.",
  commander: "Everything an analyst can do, plus approving commands and closing incidents.",
  admin: "Full access, including managing users and organization settings.",
};

/** Mirrors backend/schemas.py: MIN_PASSWORD_LENGTH and the UserCreate pattern. */
const MIN_PASSWORD_LENGTH = 12;
const USERNAME_PATTERN = /^[A-Za-z0-9._-]+$/;

function validate(username: string, password: string, confirm: string): string | null {
  if (username.length < 3) return "The username must be at least 3 characters.";
  if (username.length > 50) return "The username must be at most 50 characters.";
  if (!USERNAME_PATTERN.test(username)) {
    return "The username may contain only letters, numbers, and the characters . _ -";
  }
  if (password.length < MIN_PASSWORD_LENGTH) {
    return `The password must be at least ${MIN_PASSWORD_LENGTH} characters.`;
  }
  if (password !== confirm) return "The two passwords do not match.";
  return null;
}

export default function UsersPage() {
  const queryClient = useQueryClient();
  const { user, role } = useAuth();
  const effectiveRole = user?.role ?? role;
  const canManage = hasPermission(effectiveRole, Permissions.USER_MANAGE);

  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [newRole, setNewRole] = useState<Role>("analyst");

  const usersQuery = useQuery({
    queryKey: ["users"],
    queryFn: () => api.getUsers(),
    enabled: canManage,
  });

  const reset = () => {
    setUsername("");
    setEmail("");
    setPassword("");
    setConfirm("");
    setNewRole("analyst");
  };

  const create = useMutation({
    mutationFn: () =>
      api.createUser({
        username: username.trim(),
        password,
        email: email.trim() || undefined,
        role: newRole,
      }),
    onSuccess: (created) => {
      toast.success(`Created ${created.username} as ${humanizeEnum(created.role).toLowerCase()}`);
      reset();
      queryClient.invalidateQueries({ queryKey: ["users"] });
    },
    onError: (error: unknown) =>
      toast.error(error instanceof Error ? error.message : "Could not create the account."),
  });

  const problem = useMemo(
    () => (username || password || confirm ? validate(username.trim(), password, confirm) : null),
    [username, password, confirm],
  );

  const submittable = username.trim() !== "" && password !== "" && problem === null;

  const users = useMemo(
    () => [...(usersQuery.data ?? [])].sort((a, b) => a.username.localeCompare(b.username)),
    [usersQuery.data],
  );

  if (!canManage) {
    return (
      <>
        <PageHeader title="Team" />
        <Panel>
          <PermissionDeniedState detail="Managing accounts requires the user.manage permission, which only administrators hold." />
        </Panel>
      </>
    );
  }

  return (
    <>
      <PageHeader
        title="Team"
        description="Accounts in your organization. New accounts are created within it and cannot see another organization's data."
      />

      <div className="grid gap-4 xl:grid-cols-[340px_1fr]">
        {/* Create */}
        <Panel className="self-start">
          <PanelHeader
            title="Add an account"
            description="Created in your organization with the role you choose."
          />
          <PanelBody className="flex flex-col gap-3">
            <Field
              label="Username"
              htmlFor="new-username"
              hint="Letters, numbers, and . _ - only."
            >
              <Input
                id="new-username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                placeholder="analyst.two"
                autoComplete="off"
                autoCapitalize="none"
                spellCheck={false}
              />
            </Field>

            <Field label="Email" htmlFor="new-email" hint="Optional.">
              <Input
                id="new-email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="name@example.com"
                autoComplete="off"
              />
            </Field>

            <Field label="Role" htmlFor="new-role" hint={ROLE_SUMMARY[newRole]}>
              <Select
                id="new-role"
                value={newRole}
                onChange={(e) => setNewRole(e.target.value as Role)}
              >
                {ROLES.map((r) => (
                  <option key={r} value={r}>
                    {humanizeEnum(r)}
                  </option>
                ))}
              </Select>
            </Field>

            <Field
              label="Password"
              htmlFor="new-password"
              hint={`At least ${MIN_PASSWORD_LENGTH} characters.`}
            >
              <Input
                id="new-password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="new-password"
              />
            </Field>

            <Field label="Confirm password" htmlFor="confirm-password">
              <Input
                id="confirm-password"
                type="password"
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
                autoComplete="new-password"
              />
            </Field>

            {problem ? (
              <p role="alert" className="text-[12px] text-warning">
                {problem}
              </p>
            ) : null}

            <Button
              variant="primary"
              disabled={!submittable || create.isPending}
              loading={create.isPending}
              onClick={() => create.mutate()}
            >
              Create account
            </Button>

            <p className="flex items-start gap-2 rounded-control border border-line bg-surface-overlay px-2.5 py-2 text-[11px] leading-relaxed text-content-muted">
              <Icon name="info" size={13} className="mt-0.5 shrink-0 text-content-dim" />
              <span>
                Approving a drone command requires a different account from the one that requested
                it. An organization with a single account cannot complete that flow.
              </span>
            </p>
          </PanelBody>
        </Panel>

        {/* Roster */}
        <Panel>
          <PanelHeader
            title="Accounts"
            description={`${users.length} in your organization`}
          />

          <DataState
            isLoading={usersQuery.isLoading}
            isError={usersQuery.isError}
            error={usersQuery.error}
            data={users}
            onRetry={() => usersQuery.refetch()}
            empty={<EmptyState icon="user" title="No accounts found" />}
          >
            {(list: UserInfo[]) => (
              <>
                <div className="hidden md:block">
                  <Table>
                    <thead>
                      <tr>
                        <Th>Username</Th>
                        <Th>Role</Th>
                        <Th>Email</Th>
                        <Th>Created</Th>
                      </tr>
                    </thead>
                    <tbody>
                      {list.map((account) => (
                        <tr key={account.id} className="transition-colors hover:bg-surface-overlay">
                          <Td>
                            <Mono className="text-content">{account.username}</Mono>
                            {account.username === user?.username ? (
                              <span className="ml-2 text-[11px] text-content-dim">you</span>
                            ) : null}
                          </Td>
                          <Td>
                            <Chip
                              tone={
                                account.role === "admin"
                                  ? "critical"
                                  : account.role === "observer"
                                    ? "neutral"
                                    : "accent"
                              }
                            >
                              {humanizeEnum(account.role)}
                            </Chip>
                          </Td>
                          <Td>
                            {account.email ? (
                              <span className="text-[12px] text-content-muted">{account.email}</span>
                            ) : (
                              <span className="text-[12px] text-content-dim">Not set</span>
                            )}
                          </Td>
                          <Td>
                            <span
                              className="text-[12px] text-content-muted"
                              title={formatDateTime(account.created_at)}
                            >
                              {relativeTime(account.created_at)}
                            </span>
                          </Td>
                        </tr>
                      ))}
                    </tbody>
                  </Table>
                </div>

                <ul className="divide-y divide-line-subtle md:hidden">
                  {list.map((account) => (
                    <li key={account.id} className="flex items-center justify-between gap-2 px-4 py-3">
                      <div className="min-w-0">
                        <Mono className="text-[13px] text-content">{account.username}</Mono>
                        <p className="mt-0.5 text-[11px] text-content-dim">
                          {account.email ?? "No email"}
                        </p>
                      </div>
                      <Chip tone={account.role === "admin" ? "critical" : "accent"}>
                        {humanizeEnum(account.role)}
                      </Chip>
                    </li>
                  ))}
                </ul>
              </>
            )}
          </DataState>
        </Panel>
      </div>

      {/* What each role can do, read from the same table the console gates on. */}
      <Panel className="mt-4">
        <PanelHeader
          title="Roles"
          description="Mirrors backend/middleware/rbac.py. The backend re-checks every route; this table is what the console uses to hide controls."
        />
        <div className="overflow-x-auto">
          <Table>
            <thead>
              <tr>
                <Th>Role</Th>
                <Th>Summary</Th>
                <Th className="text-right">Permissions</Th>
              </tr>
            </thead>
            <tbody>
              {ROLES.map((r) => (
                <tr key={r}>
                  <Td>
                    <Chip tone={r === "admin" ? "critical" : r === "observer" ? "neutral" : "accent"}>
                      {humanizeEnum(r)}
                    </Chip>
                  </Td>
                  <Td>
                    <span className="text-[12px] text-content-muted">{ROLE_SUMMARY[r]}</span>
                  </Td>
                  <Td className="text-right">
                    <Mono className="text-content-muted">{permissionsFor(r).length}</Mono>
                  </Td>
                </tr>
              ))}
            </tbody>
          </Table>
        </div>
      </Panel>
    </>
  );
}
