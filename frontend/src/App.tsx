import { Link, Outlet } from "react-router-dom";

// Shell for the internal tool (spec §9). shadcn/ui to be layered in later.
export default function App() {
  return (
    <div className="min-h-screen bg-neutral-50 text-neutral-900">
      <header className="border-b bg-white">
        <nav className="mx-auto flex max-w-5xl items-center gap-6 px-6 py-3 text-sm">
          <span className="font-semibold">AI Film Pipeline</span>
          <Link className="text-neutral-600 hover:text-neutral-900" to="/submit">
            Submit
          </Link>
          <Link className="text-neutral-600 hover:text-neutral-900" to="/history">
            History
          </Link>
        </nav>
      </header>
      <main className="mx-auto max-w-5xl px-6 py-8">
        <Outlet />
      </main>
    </div>
  );
}
