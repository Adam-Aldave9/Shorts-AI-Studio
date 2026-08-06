// Auth state for the SPA. Bootstraps from `GET /auth/me` on mount (the session lives
// in an HttpOnly cookie the JS can't read, so the server is the source of truth), and
// exposes login/register/logout that update the in-memory user.

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import {
  getMe,
  login as apiLogin,
  logout as apiLogout,
  register as apiRegister,
  UnauthorizedError,
  type AuthUser,
} from "@/api/client";

interface AuthContextValue {
  user: AuthUser | null;
  loading: boolean;
  login: (username: string, password: string) => Promise<void>;
  register: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(true);

  // Bootstrap: ask the server who we are. A 401 just means "not logged in".
  useEffect(() => {
    let cancelled = false;
    getMe()
      .then((me) => !cancelled && setUser(me))
      .catch((err) => {
        if (!(err instanceof UnauthorizedError)) {
          // Non-auth errors (server down) still resolve to logged-out, but surface.
          console.error("auth bootstrap failed", err);
        }
        if (!cancelled) setUser(null);
      })
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, []);

  const login = useCallback(async (username: string, password: string) => {
    setUser(await apiLogin(username, password));
  }, []);

  const register = useCallback(async (username: string, password: string) => {
    // Registration auto-logs-in server-side (sets cookies), so adopt the new user.
    setUser(await apiRegister(username, password));
  }, []);

  const logout = useCallback(async () => {
    try {
      await apiLogout();
    } finally {
      setUser(null);
    }
  }, []);

  const value = useMemo(
    () => ({ user, loading, login, register, logout }),
    [user, loading, login, register, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

// eslint-disable-next-line react-refresh/only-export-components -- hook colocated with its provider
export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within <AuthProvider>");
  return ctx;
}
