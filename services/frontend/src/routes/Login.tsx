// Login screen. On success, return the user to the route they were headed for
// (remembered by ProtectedRoute) or the default. Errors are shown generically — the
// server never reveals whether it was the username or the password that was wrong.

import { useState, type FormEvent } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "@/auth/AuthContext";
import { Button, Card, ErrorBanner, Field, controlClass } from "@/components/ui";

interface LocationState {
  from?: { pathname: string };
}

export default function Login() {
  const navigate = useNavigate();
  const location = useLocation();
  const { login } = useAuth();
  const from = (location.state as LocationState | null)?.from?.pathname ?? "/submit";

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [pending, setPending] = useState(false);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (!username.trim() || !password) return;
    setPending(true);
    setError(null);
    try {
      await login(username.trim(), password);
      navigate(from, { replace: true });
    } catch (err) {
      setError(err);
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="mx-auto flex min-h-screen max-w-md flex-col justify-center px-6">
      <h1 className="text-2xl font-semibold">Sign in</h1>
      <p className="mt-1 text-sm text-neutral-500">
        Sign in to the AI Film Pipeline to submit briefs and monitor your runs.
      </p>

      <Card className="mt-6">
        <form className="space-y-5" onSubmit={onSubmit}>
          <Field label="Username">
            <input
              className={controlClass}
              value={username}
              autoComplete="username"
              onChange={(event) => setUsername(event.target.value)}
            />
          </Field>
          <Field label="Password">
            <input
              className={controlClass}
              type="password"
              value={password}
              autoComplete="current-password"
              onChange={(event) => setPassword(event.target.value)}
            />
          </Field>

          {error != null && <ErrorBanner title="Could not sign in" error={error} />}

          <Button type="submit" disabled={!username.trim() || !password || pending}>
            {pending ? "Signing in..." : "Sign in"}
          </Button>
        </form>
      </Card>

      <p className="mt-4 text-center text-sm text-neutral-500">
        No account?{" "}
        <Link className="font-medium text-neutral-900 hover:underline" to="/register">
          Create one
        </Link>
      </p>
    </div>
  );
}
