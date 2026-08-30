import { useState, type FormEvent } from "react";
import { useNavigate } from "@tanstack/react-router";
import { useAuth } from "@/hooks/useAuth";
import { Icon } from "@/components/ui/Icon";
import { Button, Field, Input } from "@/components/ui/primitives";

export default function LoginPage() {
  const navigate = useNavigate();
  const { login } = useAuth();

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);

    if (!username.trim() || !password) {
      setError("Enter your username and password.");
      return;
    }

    setSubmitting(true);
    try {
      await login(username.trim(), password);
      navigate({ to: "/dashboard" });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sign-in failed.");
      setPassword("");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-surface-base px-4 py-10">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex items-center gap-2.5">
          <img
            src="/logo.png"
            alt=""
            className="h-9 w-9 rounded-control border border-line-strong object-cover"
          />
          <div>
            <h1 className="text-[16px] font-semibold leading-tight text-content">SwarmGuard</h1>
            <p className="text-[12px] leading-tight text-content-dim">UAV telemetry security</p>
          </div>
        </div>

        <form
          onSubmit={handleSubmit}
          className="rounded-panel border border-line bg-surface-raised p-5"
          noValidate
        >
          <h2 className="text-[15px] font-semibold text-content">Sign in</h2>
          <p className="mt-1 text-[12px] text-content-muted">
            Access is scoped to your organization.
          </p>

          <div className="mt-4 flex flex-col gap-3.5">
            <Field label="Username or email" htmlFor="username">
              <Input
                id="username"
                name="username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                autoComplete="username"
                autoCapitalize="none"
                autoCorrect="off"
                required
                disabled={submitting}
              />
            </Field>

            <Field label="Password" htmlFor="password">
              <div className="relative">
                <Input
                  id="password"
                  name="password"
                  type={showPassword ? "text" : "password"}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  autoComplete="current-password"
                  required
                  disabled={submitting}
                  className="pr-9"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword((v) => !v)}
                  className="absolute right-1 top-1/2 flex h-7 w-7 -translate-y-1/2 items-center justify-center rounded-control text-content-dim hover:text-content"
                  tabIndex={-1}
                >
                  <Icon
                    name={showPassword ? "eye-off" : "eye"}
                    size={15}
                    title={showPassword ? "Hide password" : "Show password"}
                  />
                </button>
              </div>
            </Field>
          </div>

          {error ? (
            <p
              role="alert"
              className="mt-3.5 flex items-start gap-2 rounded-control border border-critical/35 bg-critical-wash px-2.5 py-2 text-[12px] text-critical"
            >
              <Icon name="alert" size={14} className="mt-0.5 shrink-0" />
              <span>{error}</span>
            </p>
          ) : null}

          <Button
            type="submit"
            variant="primary"
            loading={submitting}
            className="mt-4 w-full"
          >
            {submitting ? "Signing in" : "Sign in"}
          </Button>
        </form>

        <p className="mt-4 text-center text-[11px] leading-relaxed text-content-dim">
          Authorized use only. Sign-in attempts are recorded in the audit log with your IP address.
        </p>
      </div>
    </div>
  );
}
