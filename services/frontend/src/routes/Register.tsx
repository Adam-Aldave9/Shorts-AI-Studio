// Registration screen. Client-side rules mirror the server's Pydantic validators (username
// 3-32 + charset, password 12-128, confirmation match) so obvious mistakes are caught
// before a round-trip; the server stays the authority (e.g. 409 on a taken username).

import { useMemo, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "@/auth/AuthContext";
import { useAuthSubmit } from "@/hooks/useAuthSubmit";
import { Button, ErrorBanner, Field, controlClass } from "@/components/ui";
import { AuthScreen } from "@/components/AuthScreen";

const USERNAME_RE = /^[a-zA-Z0-9_.-]+$/;

function usernameError(username: string): string | null {
  if (username.length < 3 || username.length > 32) {
    return "Username must be 3–32 characters.";
  }
  if (!USERNAME_RE.test(username)) {
    return "Username may contain only letters, digits, '.', '_' and '-'.";
  }
  return null;
}

function passwordError(password: string): string | null {
  if (password.length < 12 || password.length > 128) {
    return "Password must be 12–128 characters.";
  }
  return null;
}

export default function Register() {
  const navigate = useNavigate();
  const { register } = useAuth();

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const { error, pending, submit } = useAuthSubmit(async () => {
    await register(username.trim(), password);
    navigate("/submit", { replace: true });
  });

  // Only surface a client-side rule once the user has typed something in the field.
  const clientError = useMemo(() => {
    if (username && usernameError(username)) return usernameError(username);
    if (password && passwordError(password)) return passwordError(password);
    if (confirm && password !== confirm) return "Passwords do not match.";
    return null;
  }, [username, password, confirm]);

  const canSubmit =
    !usernameError(username) && !passwordError(password) && password === confirm && !pending;

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (!canSubmit) return;
    await submit();
  }

  return (
    <AuthScreen
      title="Create an account"
      subtitle="Sign up to submit briefs and manage your own runs."
      footer={
        <>
          Already have an account?{" "}
          <Link
            className="font-medium text-accent-soft hover:text-accent hover:underline"
            to="/login"
          >
            Sign in
          </Link>
        </>
      }
    >
      <form className="space-y-5" onSubmit={onSubmit}>
        <Field label="Username" hint="3–32 chars: letters, digits, . _ -">
          <input
            className={controlClass}
            value={username}
            autoComplete="username"
            autoFocus
            onChange={(event) => setUsername(event.target.value)}
          />
        </Field>
        <Field label="Password" hint="at least 12 characters">
          <input
            className={controlClass}
            type="password"
            value={password}
            autoComplete="new-password"
            onChange={(event) => setPassword(event.target.value)}
          />
        </Field>
        <Field label="Confirm password">
          <input
            className={controlClass}
            type="password"
            value={confirm}
            autoComplete="new-password"
            onChange={(event) => setConfirm(event.target.value)}
          />
        </Field>

        {clientError && (
          <div className="rounded-md border border-warning/30 bg-warning/10 px-4 py-3 text-sm text-warning">
            {clientError}
          </div>
        )}
        {error != null && <ErrorBanner title="Could not create account" error={error} />}

        <Button type="submit" disabled={!canSubmit}>
          {pending ? "Creating..." : "Create account"}
        </Button>
      </form>
    </AuthScreen>
  );
}
