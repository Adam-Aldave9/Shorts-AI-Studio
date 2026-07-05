// Registration screen. Client-side rules mirror the server's Pydantic validators
// (username 3-32 + charset, password 12-128, confirmation match) so obvious mistakes
// are caught before a round-trip; the server remains the authority (e.g. 409 on a
// taken username).

import { useMemo, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "@/auth/AuthContext";
import { Button, Card, ErrorBanner, Field, controlClass } from "@/components/ui";

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
  const [error, setError] = useState<unknown>(null);
  const [pending, setPending] = useState(false);

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
    setPending(true);
    setError(null);
    try {
      await register(username.trim(), password);
      navigate("/submit", { replace: true });
    } catch (err) {
      setError(err);
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="mx-auto flex min-h-screen max-w-md flex-col justify-center px-6">
      <h1 className="text-2xl font-semibold">Create an account</h1>
      <p className="mt-1 text-sm text-neutral-500">
        Sign up to submit briefs and manage your own runs.
      </p>

      <Card className="mt-6">
        <form className="space-y-5" onSubmit={onSubmit}>
          <Field label="Username" hint="3–32 chars: letters, digits, . _ -">
            <input
              className={controlClass}
              value={username}
              autoComplete="username"
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
            <div className="rounded-md border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-800">
              {clientError}
            </div>
          )}
          {error != null && <ErrorBanner title="Could not create account" error={error} />}

          <Button type="submit" disabled={!canSubmit}>
            {pending ? "Creating..." : "Create account"}
          </Button>
        </form>
      </Card>

      <p className="mt-4 text-center text-sm text-neutral-500">
        Already have an account?{" "}
        <Link className="font-medium text-neutral-900 hover:underline" to="/login">
          Sign in
        </Link>
      </p>
    </div>
  );
}
