// Login screen. On success, return the user to the route they were headed for (remembered
// by ProtectedRoute) or the default. Errors are generic — the server never reveals whether
// the username or the password was wrong.

import { useState, type FormEvent } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "@/auth/AuthContext";
import { useAuthSubmit } from "@/hooks/useAuthSubmit";
import { Button, ErrorBanner, Field, controlClass } from "@/components/ui";
import { AuthScreen } from "@/components/AuthScreen";

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
  const { error, pending, submit } = useAuthSubmit(async () => {
    await login(username.trim(), password);
    navigate(from, { replace: true });
  });

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (!username.trim() || !password) return;
    await submit();
  }

  return (
    <AuthScreen
      title="Sign in"
      subtitle="Sign in to the AI Film Pipeline to submit briefs and monitor your runs."
      footer={
        <>
          No account?{" "}
          <Link
            className="font-medium text-accent-soft hover:text-accent hover:underline"
            to="/register"
          >
            Create one
          </Link>
        </>
      }
    >
      <form className="space-y-5" onSubmit={onSubmit}>
        <Field label="Username">
          <input
            className={controlClass}
            value={username}
            autoComplete="username"
            autoFocus
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
    </AuthScreen>
  );
}
