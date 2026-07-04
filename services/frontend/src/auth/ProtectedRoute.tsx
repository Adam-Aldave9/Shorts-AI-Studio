// Route guard: renders the protected tree only when authenticated. While the session
// is still being bootstrapped we show a spinner (avoids a flash of the login screen
// for an already-logged-in user); once known, an unauthenticated user is redirected
// to /login with their intended location remembered for post-login return.

import { Navigate, Outlet, useLocation } from "react-router-dom";
import { useAuth } from "@/auth/AuthContext";
import { Spinner } from "@/components/ui";

export default function ProtectedRoute() {
  const { user, loading } = useAuth();
  const location = useLocation();

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <Spinner label="Loading..." />
      </div>
    );
  }

  if (!user) {
    return <Navigate to="/login" replace state={{ from: location }} />;
  }

  return <Outlet />;
}
