/**
 * Account and session.
 *
 * The permission list is rendered from the client-side RBAC mirror and labelled
 * as such — it reflects what the console will offer, while the backend remains
 * the authority on every request.
 */

import { useState, type FormEvent } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { api } from "@/services/api";
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
} from "@/components/ui/primitives";
import { LoadingState } from "@/components/ui/DataState";
import { formatDateTime, humanizeEnum } from "@/lib/format";
import { permissionsFor } from "@/lib/rbac";
import { useAuth } from "@/hooks/useAuth";

const MIN_PASSWORD_LENGTH = 12;

export default function ProfilePage() {
  const queryClient = useQueryClient();
  const { user, isLoading, logout } = useAuth();

  const [email, setEmail] = useState("");
  const [emailTouched, setEmailTouched] = useState(false);

  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [passwordError, setPasswordError] = useState<string | null>(null);

  const updateEmail = useMutation({
    mutationFn: (value: string) => api.updateMe({ email: value }),
    onSuccess: () => {
      toast.success("Email updated");
      setEmailTouched(false);
      queryClient.invalidateQueries({ queryKey: ["me"] });
    },
    onError: (error: unknown) =>
      toast.error(error instanceof Error ? error.message : "Could not update your email."),
  });

  const changePassword = useMutation({
    mutationFn: () => api.changePassword(currentPassword, newPassword),
    onSuccess: () => {
      toast.success("Password changed. Existing sessions remain valid until their token expires.");
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
      setPasswordError(null);
    },
    onError: (error: unknown) =>
      setPasswordError(
        error instanceof Error ? error.message : "Could not change your password.",
      ),
  });

  if (isLoading) {
    return (
      <>
        <PageHeader title="Profile" />
        <Panel>
          <LoadingState rows={5} />
        </Panel>
      </>
    );
  }

  if (!user) {
    return (
      <>
        <PageHeader title="Profile" />
        <Panel>
          <PanelBody>
            <p className="text-[13px] text-content-muted">
              Your profile could not be loaded. Sign out and back in to retry.
            </p>
            <Button className="mt-3" size="sm" onClick={logout}>
              Sign out
            </Button>
          </PanelBody>
        </Panel>
      </>
    );
  }

  const permissions = permissionsFor(user.role);
  const emailValue = emailTouched ? email : (user.email ?? "");

  function handlePasswordSubmit(event: FormEvent) {
    event.preventDefault();
    setPasswordError(null);

    if (!currentPassword) return setPasswordError("Enter your current password.");
    if (newPassword.length < MIN_PASSWORD_LENGTH)
      return setPasswordError(`Use at least ${MIN_PASSWORD_LENGTH} characters.`);
    if (newPassword !== confirmPassword) return setPasswordError("The new passwords do not match.");
    if (newPassword === currentPassword)
      return setPasswordError("The new password must differ from the current one.");

    changePassword.mutate();
  }

  return (
    <>
      <PageHeader title="Profile" description="Your account and what it can do." />

      <div className="grid gap-4 lg:grid-cols-2">
        <div className="flex flex-col gap-4">
          <Panel>
            <PanelHeader title="Account" />
            <PanelBody>
              <div className="flex items-center gap-3">
                <span
                  aria-hidden="true"
                  className="flex h-11 w-11 items-center justify-center rounded-full border border-line-strong bg-surface-overlay text-[16px] font-semibold text-content-muted"
                >
                  {user.username.charAt(0).toUpperCase()}
                </span>
                <div className="min-w-0">
                  <p className="truncate text-[15px] font-semibold text-content">{user.username}</p>
                  <p className="mt-0.5 flex items-center gap-2">
                    <Chip tone="accent">{humanizeEnum(user.role)}</Chip>
                  </p>
                </div>
              </div>

              <dl className="mt-4 grid grid-cols-2 gap-x-4 gap-y-3">
                <div>
                  <dt className="text-[11px] text-content-dim">User ID</dt>
                  <dd className="mt-0.5">
                    <Mono className="text-content">{user.id}</Mono>
                  </dd>
                </div>
                <div>
                  <dt className="text-[11px] text-content-dim">Organization</dt>
                  <dd className="mt-0.5">
                    {user.organization_id !== null && user.organization_id !== undefined ? (
                      <Mono className="text-content">{user.organization_id}</Mono>
                    ) : (
                      <span className="text-[12px] text-warning">Not assigned</span>
                    )}
                  </dd>
                </div>
                <div className="col-span-2">
                  <dt className="text-[11px] text-content-dim">Created</dt>
                  <dd className="mt-0.5 text-[13px] text-content">
                    {formatDateTime(user.created_at)}
                  </dd>
                </div>
              </dl>

              {user.organization_id === null || user.organization_id === undefined ? (
                <p className="mt-3 flex items-start gap-2 rounded-control border border-warning/35 bg-warning-wash px-2.5 py-2 text-[12px] text-warning">
                  <Icon name="alert" size={13} className="mt-0.5 shrink-0" />
                  <span>
                    This account is not assigned to an organization, so tenant-scoped views will
                    return no data. An administrator must assign it.
                  </span>
                </p>
              ) : null}
            </PanelBody>
          </Panel>

          <Panel>
            <PanelHeader title="Contact" />
            <PanelBody>
              <Field label="Email" htmlFor="profile-email">
                <Input
                  id="profile-email"
                  type="email"
                  value={emailValue}
                  onChange={(e) => {
                    setEmail(e.target.value);
                    setEmailTouched(true);
                  }}
                  placeholder="name@example.com"
                  autoComplete="email"
                />
              </Field>
              <Button
                size="sm"
                className="mt-3"
                disabled={!emailTouched || updateEmail.isPending}
                loading={updateEmail.isPending}
                onClick={() => updateEmail.mutate(email.trim())}
              >
                Update email
              </Button>
            </PanelBody>
          </Panel>
        </div>

        <div className="flex flex-col gap-4">
          <Panel>
            <PanelHeader title="Change password" description={`Minimum ${MIN_PASSWORD_LENGTH} characters.`} />
            <PanelBody>
              <form onSubmit={handlePasswordSubmit} className="flex flex-col gap-3" noValidate>
                <Field label="Current password" htmlFor="current-password">
                  <Input
                    id="current-password"
                    type="password"
                    value={currentPassword}
                    onChange={(e) => setCurrentPassword(e.target.value)}
                    autoComplete="current-password"
                  />
                </Field>

                <Field label="New password" htmlFor="new-password">
                  <Input
                    id="new-password"
                    type="password"
                    value={newPassword}
                    onChange={(e) => setNewPassword(e.target.value)}
                    autoComplete="new-password"
                  />
                </Field>

                <Field label="Confirm new password" htmlFor="confirm-password" error={passwordError ?? undefined}>
                  <Input
                    id="confirm-password"
                    type="password"
                    value={confirmPassword}
                    onChange={(e) => setConfirmPassword(e.target.value)}
                    autoComplete="new-password"
                  />
                </Field>

                <Button
                  type="submit"
                  variant="primary"
                  size="sm"
                  className="self-start"
                  loading={changePassword.isPending}
                >
                  Change password
                </Button>
              </form>

              <p className="mt-3 flex items-start gap-2 rounded-control border border-line bg-surface-overlay px-2.5 py-2 text-[11px] leading-relaxed text-content-muted">
                <Icon name="info" size={13} className="mt-0.5 shrink-0 text-content-dim" />
                <span>
                  Changing your password does not invalidate tokens already issued. Any existing
                  session stays valid until its token expires.
                </span>
              </p>
            </PanelBody>
          </Panel>

          <Panel>
            <PanelHeader
              title="Permissions"
              description="What this console will offer your role. The backend enforces access independently."
            />
            <PanelBody>
              {permissions.length === 0 ? (
                <p className="text-[13px] text-content-muted">
                  No permissions are mapped for the role “{user.role}”. Views will report access
                  denied.
                </p>
              ) : (
                <ul className="flex flex-wrap gap-1.5">
                  {permissions.map((permission) => (
                    <li key={permission}>
                      <Chip>
                        <Mono className="text-[11px]">{permission}</Mono>
                      </Chip>
                    </li>
                  ))}
                </ul>
              )}
            </PanelBody>
          </Panel>

          <Panel>
            <PanelBody>
              <Button variant="danger" size="sm" icon="logout" onClick={logout}>
                Sign out
              </Button>
            </PanelBody>
          </Panel>
        </div>
      </div>
    </>
  );
}
