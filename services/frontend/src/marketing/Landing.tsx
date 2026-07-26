// Public marketing landing at `/` — always viewable; logged-in users get "Open studio"
// CTAs instead of sign-up prompts (via useAuth). Self-contained: no external assets, all
// classes come from the design tokens so it themes/purges with the rest of the app.

import { Link } from "react-router-dom";
import type { ReactNode } from "react";
import { useAuth } from "@/auth/AuthContext";
import { Logo } from "@/components/Logo";

const CTA_BASE =
  "inline-flex items-center justify-center rounded-md px-4 py-2 text-sm font-medium transition " +
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/60 focus-visible:ring-offset-2 focus-visible:ring-offset-surface";

function PrimaryCta({ to, children }: { to: string; children: ReactNode }) {
  return (
    <Link to={to} className={`${CTA_BASE} bg-accent-strong text-white hover:bg-accent`}>
      {children}
    </Link>
  );
}

function SecondaryCta({ to, children }: { to: string; children: ReactNode }) {
  const cls = `${CTA_BASE} border border-border bg-surface-raised text-fg hover:border-border-strong hover:bg-surface-overlay`;
  // Bare in-page anchors need a real <a> for the native scroll-to-id jump.
  if (to.startsWith("#")) {
    return (
      <a href={to} className={cls}>
        {children}
      </a>
    );
  }
  return (
    <Link to={to} className={cls}>
      {children}
    </Link>
  );
}

function Nav() {
  const { user } = useAuth();
  return (
    <header className="sticky top-0 z-10 border-b border-border bg-surface/80 backdrop-blur">
      <nav className="mx-auto flex max-w-6xl items-center gap-6 px-6 py-3">
        <Link to="/">
          <Logo withWordmark />
        </Link>
        <div className="ml-auto flex items-center gap-2 sm:gap-3">
          {user ? (
            <PrimaryCta to="/submit">Open studio</PrimaryCta>
          ) : (
            <>
              <a
                href="#how-it-works"
                className="hidden px-3 py-2 text-sm text-fg-muted hover:text-fg sm:inline"
              >
                How it works
              </a>
              <Link
                to="/login"
                className={`${CTA_BASE} text-fg-muted hover:bg-surface-overlay hover:text-fg`}
              >
                Sign in
              </Link>
              <PrimaryCta to="/register">Get started</PrimaryCta>
            </>
          )}
        </div>
      </nav>
    </header>
  );
}

// Animated DAG mirroring the real topology: one brief -> fan-out to shots + a
// voiceover -> converge into the final cut. Both animations freeze under the
// prefers-reduced-motion block in index.css.
function PipelineDiagram() {
  const shotYs = [40, 96, 152, 208, 264];
  const briefX = 60;
  const shotX = 240;
  const finalX = 420;
  const briefY = 160;
  const voiceY = 300;
  const nodes = [...shotYs.map((y) => ({ x: shotX, y })), { x: shotX, y: voiceY }];

  return (
    <div className="rounded-xl border bg-surface-raised p-6">
      <svg viewBox="0 0 480 320" className="h-auto w-full" role="img" aria-label="Pipeline DAG">
        {nodes.map((n, i) => {
          const d = `M ${briefX + 14} ${briefY} C ${(briefX + n.x) / 2} ${briefY}, ${(briefX + n.x) / 2} ${n.y}, ${n.x - 14} ${n.y}`;
          return (
            <g key={`in-${i}`}>
              <path d={d} fill="none" stroke="rgb(var(--color-border-strong))" strokeWidth="2" />
              <path
                d={d}
                fill="none"
                stroke="rgb(var(--color-accent))"
                strokeWidth="2"
                strokeDasharray="6 10"
                className="animate-dag-flow"
                style={{ animationDelay: `${i * 0.2}s` }}
              />
            </g>
          );
        })}
        {nodes.map((n, i) => {
          const d = `M ${n.x + 14} ${n.y} C ${(n.x + finalX) / 2} ${n.y}, ${(n.x + finalX) / 2} ${briefY}, ${finalX - 16} ${briefY}`;
          return (
            <g key={`out-${i}`}>
              <path d={d} fill="none" stroke="rgb(var(--color-border-strong))" strokeWidth="2" />
              <path
                d={d}
                fill="none"
                stroke="rgb(var(--color-accent))"
                strokeWidth="2"
                strokeDasharray="6 10"
                className="animate-dag-flow"
                style={{ animationDelay: `${i * 0.2 + 0.6}s` }}
              />
            </g>
          );
        })}

        <circle
          cx={briefX}
          cy={briefY}
          r="14"
          fill="rgb(var(--color-surface-overlay))"
          stroke="rgb(var(--color-accent-soft))"
          strokeWidth="2"
        />
        <text
          x={briefX}
          y={briefY + 30}
          textAnchor="middle"
          className="text-[10px]"
          fill="rgb(var(--color-fg-subtle))"
        >
          brief
        </text>

        {/* shot + voiceover nodes: one done (green), one rendering (blue pulse), rest pending */}
        {shotYs.map((y, i) => {
          const done = i === 0;
          const rendering = i === 1;
          const stroke = done
            ? "rgb(34 197 94)"
            : rendering
              ? "rgb(59 130 246)"
              : "rgb(var(--color-border-strong))";
          return (
            <g key={`shot-${i}`}>
              <circle
                cx={shotX}
                cy={y}
                r="12"
                fill="rgb(var(--color-surface-overlay))"
                stroke={stroke}
                strokeWidth="2"
                className={rendering ? "animate-node-pulse" : undefined}
              />
              <text
                x={shotX + 20}
                y={y + 4}
                className="text-[10px]"
                fill="rgb(var(--color-fg-subtle))"
              >
                {`shot-0${i + 1}`}
              </text>
            </g>
          );
        })}
        <circle
          cx={shotX}
          cy={voiceY}
          r="12"
          fill="rgb(var(--color-surface-overlay))"
          stroke="rgb(var(--color-accent-soft))"
          strokeWidth="2"
        />
        <text
          x={shotX + 20}
          y={voiceY + 4}
          className="text-[10px]"
          fill="rgb(var(--color-fg-subtle))"
        >
          voiceover
        </text>

        <circle
          cx={finalX}
          cy={briefY}
          r="18"
          fill="rgb(var(--color-surface-overlay))"
          stroke="rgb(var(--color-accent))"
          strokeWidth="2"
        />
        <path d={`M ${finalX - 5} ${briefY - 7} v 14 l 11 -7 z`} fill="rgb(var(--color-accent))" />
        <text
          x={finalX}
          y={briefY + 34}
          textAnchor="middle"
          className="text-[10px]"
          fill="rgb(var(--color-fg-subtle))"
        >
          final.mp4
        </text>
      </svg>
    </div>
  );
}

function Hero() {
  const { user } = useAuth();
  return (
    <section className="relative overflow-hidden">
      <div className="pointer-events-none absolute inset-x-0 top-0 h-96 bg-accent/10 blur-3xl [clip-path:ellipse(60%_50%_at_50%_0%)]" />
      <div className="mx-auto grid max-w-6xl gap-12 px-6 py-20 lg:grid-cols-2 lg:items-center lg:py-28">
        <div>
          <p className="text-xs font-medium uppercase tracking-widest text-accent-soft">
            AI-planned · human-approved · fleet-rendered
          </p>
          <h1 className="mt-4 text-4xl font-semibold tracking-tight sm:text-6xl">
            One sentence in.
            <br />
            <span className="text-accent-soft">One film out.</span>
          </h1>
          <p className="mt-6 max-w-xl text-lg text-fg-muted">
            Describe a film in a single brief. AI agents build the world, write the script, and plan
            every shot. You approve the plan — then a distributed worker fleet renders it in
            parallel and hands you a narrated MP4.
          </p>
          <div className="mt-8 flex flex-wrap items-center gap-3">
            {user ? (
              <PrimaryCta to="/submit">Open studio</PrimaryCta>
            ) : (
              <PrimaryCta to="/register">Start a film — it's free</PrimaryCta>
            )}
            <SecondaryCta to="#how-it-works">See how it works</SecondaryCta>
          </div>
          <p className="mt-6 text-sm text-fg-subtle">
            No API keys required — the entire pipeline runs offline in mock mode.
          </p>
        </div>
        <PipelineDiagram />
      </div>
    </section>
  );
}

const STEPS = [
  {
    title: "Write the brief",
    body: "A premise, a duration, a style, a voice. That's the whole input.",
  },
  {
    title: "Agents plan the film",
    body: "A LangGraph chain builds the world, writes the script, breaks it into shots, and writes a render prompt for every one.",
  },
  {
    title: "You hold the gate",
    body: "Nothing renders until you approve. Review the production package, edit the JSON with live schema validation, check the cost estimate.",
  },
  {
    title: "The fleet renders",
    body: "A scheduler walks the shot DAG and dispatches ready nodes to parallel workers — watch every retry, cost tick, and status change live.",
  },
  {
    title: "Premiere",
    body: "FFmpeg stitches shots and narration into the final cut. Play it, download the MP4, audit estimated vs actual spend per node.",
  },
];

function HowItWorks() {
  return (
    <section id="how-it-works" className="border-t border-border">
      <div className="mx-auto max-w-6xl px-6 py-20">
        <h2 className="text-3xl font-semibold tracking-tight">From premise to premiere</h2>
        <p className="mt-3 max-w-2xl text-fg-muted">
          The same five stages every run takes — with you holding the only gate.
        </p>
        <ol className="mt-10 grid gap-4 lg:grid-cols-5">
          {STEPS.map((step, i) => (
            <li key={step.title} className="rounded-xl border bg-surface-raised p-5">
              <div className="flex h-8 w-8 items-center justify-center rounded-full bg-accent/15 text-sm font-semibold text-accent-soft">
                {i + 1}
              </div>
              <h3 className="mt-4 font-medium text-fg">{step.title}</h3>
              <p className="mt-2 text-sm text-fg-muted">{step.body}</p>
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}

// A minimal glyph set — simple line icons in currentColor (text-accent-soft).
function Glyph({ path }: { path: ReactNode }) {
  return (
    <svg
      viewBox="0 0 24 24"
      className="h-5 w-5 text-accent-soft"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {path}
    </svg>
  );
}

const FEATURES = [
  {
    glyph: <path d="M9 12l2 2 4-4M12 3l7 4v5c0 4-3 7-7 9-4-2-7-5-7-9V7z" />,
    title: "Human-in-the-loop checkpoint",
    body: "Every plan stops at an approval gate: a rendered summary beside the raw package JSON, schema-validated as you type. You're the executive producer.",
  },
  {
    glyph: (
      <>
        <circle cx="12" cy="12" r="9" />
        <path d="M12 7v5l3 3" />
      </>
    ),
    title: "Live execution view",
    body: "Server-sent events stream every node the moment it changes — in flight, queued, succeeded, failed, dead-lettered.",
  },
  {
    glyph: (
      <>
        <circle cx="12" cy="12" r="9" />
        <path d="M12 7v10M9.5 9.5a2.5 2 0 015 0c0 2.5-5 1-5 4a2.5 2 0 005 0" />
      </>
    ),
    title: "Cost you can see",
    body: "Per-shot estimates before you approve, actuals as they land, and a budget gate that stops dispatch before overspend.",
  },
  {
    glyph: (
      <>
        <circle cx="6" cy="12" r="2" />
        <circle cx="18" cy="6" r="2" />
        <circle cx="18" cy="18" r="2" />
        <path d="M8 12h4M16 7l-4 4M16 17l-4-4" />
      </>
    ),
    title: "Parallel by design",
    body: "Shots render concurrently across a worker fleet; the DAG's critical path — not the shot count — sets the wall-clock floor.",
  },
  {
    glyph: (
      <path d="M12 9v4M12 17h.01M10.3 4.3L2.6 18a2 2 0 001.7 3h15.4a2 2 0 001.7-3L13.7 4.3a2 2 0 00-3.4 0z" />
    ),
    title: "Fails loud, retries quiet",
    body: "Transient provider errors back off and retry automatically; permanent ones dead-letter with the error in view, never lost.",
  },
  {
    glyph: (
      <>
        <path d="M4 7V5a1 1 0 011-1h14a1 1 0 011 1v2" />
        <rect x="3" y="7" width="18" height="12" rx="2" />
        <path d="M8 12h8" />
      </>
    ),
    title: "A $0 dev mode",
    body: "Mock mode swaps every paid provider for a stub and runs the full pipeline offline — same UI, same DAG, no keys, no spend.",
  },
];

function Features() {
  return (
    <section className="border-t border-border">
      <div className="mx-auto max-w-6xl px-6 py-20">
        <h2 className="text-3xl font-semibold tracking-tight">
          Built like a studio, run like a system
        </h2>
        <div className="mt-10 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {FEATURES.map((f) => (
            <div key={f.title} className="rounded-xl border bg-surface-raised p-5">
              <Glyph path={f.glyph} />
              <h3 className="mt-4 font-medium text-fg">{f.title}</h3>
              <p className="mt-2 text-sm text-fg-muted">{f.body}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

const STACK = [
  "React + Vite",
  "FastAPI",
  "LangGraph",
  "Celery",
  "Redis",
  "Postgres",
  "MinIO",
  "FFmpeg",
  "Server-Sent Events",
  "Docker Compose",
];

function UnderTheHood() {
  return (
    <section className="border-t border-border">
      <div className="mx-auto max-w-6xl px-6 py-20">
        <h2 className="text-3xl font-semibold tracking-tight">Under the hood</h2>
        <p className="mt-3 max-w-2xl text-fg-muted">
          A real distributed system end to end — two tiers separated by a single JSON contract.
        </p>
        <div className="mt-8 flex flex-wrap gap-2">
          {STACK.map((chip) => (
            <span
              key={chip}
              className="rounded-full border border-border bg-surface-raised px-3 py-1 text-xs text-fg-muted"
            >
              {chip}
            </span>
          ))}
        </div>
      </div>
    </section>
  );
}

function CtaBand() {
  const { user } = useAuth();
  return (
    <section className="mx-auto max-w-6xl px-6 py-20">
      <div className="rounded-2xl border border-accent/20 bg-accent/5 px-6 py-16 text-center">
        <h2 className="text-3xl font-semibold tracking-tight">Ready to direct?</h2>
        <p className="mt-3 text-fg-muted">Your first film is one sentence away.</p>
        <div className="mt-8 flex flex-wrap items-center justify-center gap-3">
          {user ? (
            <PrimaryCta to="/submit">Open studio</PrimaryCta>
          ) : (
            <>
              <PrimaryCta to="/register">Create a free account</PrimaryCta>
              <SecondaryCta to="/login">Sign in</SecondaryCta>
            </>
          )}
        </div>
      </div>
    </section>
  );
}

function Footer() {
  return (
    <footer className="border-t border-border">
      <div className="mx-auto flex max-w-6xl flex-col gap-4 px-6 py-10 text-sm text-fg-subtle sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-3">
          <Logo />
          <span>AI Film Pipeline — a distributed-systems portfolio project.</span>
        </div>
        <div className="flex items-center gap-4">
          <a href="#how-it-works" className="hover:text-fg">
            How it works
          </a>
          <Link to="/login" className="hover:text-fg">
            Sign in
          </Link>
          <Link to="/register" className="hover:text-fg">
            Create account
          </Link>
        </div>
      </div>
    </footer>
  );
}

export default function Landing() {
  return (
    <div className="min-h-screen">
      <Nav />
      <main>
        <Hero />
        <HowItWorks />
        <Features />
        <UnderTheHood />
        <CtaBand />
      </main>
      <Footer />
    </div>
  );
}
