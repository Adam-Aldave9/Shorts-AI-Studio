import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { useAuth } from "@/auth/AuthContext";
import { Button } from "@/components/ui";

const navLinkClass = ({ isActive }: { isActive: boolean }) =>
  isActive ? "font-medium text-neutral-900" : "text-neutral-600 hover:text-neutral-900";

// Shell for the internal tool (spec §9).
export default function App() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  async function onLogout() {
    await logout();
    navigate("/login", { replace: true });
  }

  return (
    <div className="min-h-screen bg-neutral-50 text-neutral-900">
      <header className="border-b bg-white">
        <nav className="mx-auto flex max-w-5xl items-center gap-6 px-6 py-3 text-sm">
          <span className="font-semibold">AI Film Pipeline</span>
          <NavLink className={navLinkClass} to="/submit">
            Submit
          </NavLink>
          <NavLink className={navLinkClass} to="/history">
            History
          </NavLink>
          <div className="ml-auto flex items-center gap-3">
            {user && <span className="text-neutral-600">{user.username}</span>}
            <Button variant="ghost" onClick={onLogout}>
              Log out
            </Button>
          </div>
        </nav>
      </header>
      <main className="mx-auto max-w-5xl px-6 py-8">
        <Outlet />
      </main>
    </div>
  );
}
