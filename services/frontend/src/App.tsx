import { Link, NavLink, Outlet, useNavigate } from "react-router-dom";
import { useAuth } from "@/auth/AuthContext";
import { Button } from "@/components/ui";
import { Logo } from "@/components/Logo";

const navLinkClass = ({ isActive }: { isActive: boolean }) =>
  isActive ? "font-medium text-fg" : "text-fg-muted hover:text-fg";

// Shell for the internal tool (spec §9).
export default function App() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  async function onLogout() {
    await logout();
    navigate("/", { replace: true });
  }

  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-10 border-b border-border bg-surface/80 backdrop-blur">
        <nav className="mx-auto flex max-w-5xl items-center gap-6 px-6 py-3 text-sm">
          <Link to="/">
            <Logo withWordmark />
          </Link>
          <NavLink className={navLinkClass} to="/submit">
            Submit
          </NavLink>
          <NavLink className={navLinkClass} to="/history">
            History
          </NavLink>
          <div className="ml-auto flex items-center gap-3">
            {user && <span className="hidden text-fg-subtle sm:inline">{user.username}</span>}
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
