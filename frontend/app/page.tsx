"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import GitHubStars from "@/components/GitHubStars";

export default function Landing() {
  const [authed, setAuthed] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  useEffect(() => { api.me().then(() => setAuthed(true)).catch(() => {}); }, []);
  const primary = authed ? { href: "/traces", label: "Open portal" } : { href: "/signup", label: "Get started free" };
  const navLinks = (
    <>
      <a href="#features" onClick={() => setMenuOpen(false)}>Features</a>
      <a href="#flow" onClick={() => setMenuOpen(false)}>Agent flow</a>
      <Link href="/blog" onClick={() => setMenuOpen(false)}>Blog</Link>
      <a href="https://github.com/MobirizerServices/ProveKit" target="_blank" rel="noreferrer">GitHub</a>
      {!authed && <Link href="/login">Sign in</Link>}
    </>
  );

  const ld = {
    "@context": "https://schema.org", "@type": "SoftwareApplication",
    name: "ProveKit", applicationCategory: "DeveloperApplication", operatingSystem: "Any",
    description: "Drop-in tracing, evaluation, and observability for AI agents. Open source and self-hostable.",
    offers: { "@type": "Offer", price: "0", priceCurrency: "USD" },
    url: "https://github.com/MobirizerServices/ProveKit",
  };

  return (
    <div className="lp">
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(ld) }} />
      <header className="lp-nav">
        <div className="lp-brand"><span className="lp-logo">◇</span> Prove<b>Kit</b></div>
        <nav className="lp-navlinks">
          <span className="lp-navdesktop">{navLinks}</span>
          <Link href={authed ? "/traces" : "/signup"} className="lp-signin">{authed ? "Portal" : "Sign up"}</Link>
          <button className="lp-burger" aria-label="Menu" aria-expanded={menuOpen} onClick={() => setMenuOpen((o) => !o)}>
            {menuOpen ? "✕" : "☰"}
          </button>
        </nav>
      </header>
      {menuOpen && <div className="lp-mobilemenu">{navLinks}</div>}

      <section className="lp-hero">
        <div className="lp-hero-copy">
          <div className="lp-pill">Open source · Self-hostable · OpenTelemetry-native</div>
          <h1>See exactly what your AI agent did.</h1>
          <p>
            Add <b>one decorator</b> and every run your agent makes — the model calls, the tools,
            the retries, the whole nested flow — shows up in your portal. Then evaluate it, watch
            it, and gate your CI on it. No connections to wire, no framework lock-in.
          </p>
          <div className="lp-cta">
            <Link href={primary.href} className="btn lp-btn-primary">{primary.label}</Link>
            <a href="#how" className="btn btn-ghost lp-btn">See how it works</a>
          </div>
          <div className="lp-trust">
            <span>◆ One SDK, zero lock-in</span><span>◆ Traces · Evals · Dashboards</span><span>◆ Docker / Compose</span>
          </div>
          <p className="lp-whofor">For engineers building agents on OpenAI, Anthropic, LangChain, LlamaIndex, or CrewAI.</p>
        </div>
        <TracePreview />
      </section>

      <section className="lp-logos">
        <div className="lp-logos-label">Captures the tools you already use</div>
        <div className="lp-logos-row">
          {["OpenAI", "Anthropic", "LangChain", "LlamaIndex", "CrewAI", "OpenTelemetry"].map((n) => (
            <span key={n} className="lp-logo-chip">{n}</span>
          ))}
        </div>
      </section>

      <section className="lp-code-band">
        <div className="lp-code-copy">
          <h2>Two lines to your first trace.</h2>
          <p>
            The SDK auto-instruments OpenAI, Anthropic, LangChain, LlamaIndex, CrewAI and more —
            plus your outbound HTTP — so you capture the full flow with no per-call wiring.
          </p>
          <ul className="lp-check">
            <li>Fail-open by design — tracing never takes your agent down.</li>
            <li>Nested spans classified agent · llm · tool · step.</li>
            <li>Tokens, cost, latency, logs, and errors on every span.</li>
          </ul>
        </div>
        <pre className="lp-code">{`pip install "provekit[trace]"

# .env
PROVEKIT_API_KEY=pk_...
PROVEKIT_ENDPOINT=https://your-host

import provekit.auto          # one import — captures everything

# optional: group a run under a named root
import provekit.trace as pk

@pk.trace(name="support-agent")
def run(question):
    ...   # OpenAI / Anthropic / tools capture themselves`}</pre>
      </section>

      <section id="flow" className="lp-flowsec">
        <h2 className="lp-h2">The whole agent flow, as it ran.</h2>
        <p className="lp-sub">Nested agents, tool calls, retries and failures — a live node graph with the execution path lit up.</p>
        <FlowVisual />
      </section>

      <section className="lp-demo">
        <h2 className="lp-h2">See it in action</h2>
        <p className="lp-sub">A real 37-span run — nested sub-agents, RAG retrieval, a failed-then-retried tool — in the Flow and Waterfall views.</p>
        <div className="lp-demo-frame">
          <div className="lp-demo-bar"><span className="lp-dot r" /><span className="lp-dot y" /><span className="lp-dot g" /></div>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src="/demo-trace.gif" alt="ProveKit portal showing an agent trace as a node graph and a waterfall"
            loading="lazy" width={1512} height={697} className="lp-demo-img" />
        </div>
      </section>

      <section id="features" className="lp-features">
        <h2 className="lp-h2">Everything to prove your agent works</h2>
        <p className="lp-sub">From the first trace to a CI regression gate — one platform, self-hostable.</p>
        <div className="lp-grid">
          {FEATURES.map((f) => (
            <div key={f.t} className="lp-card">
              <div className="lp-card-ic" style={{ color: f.c }}>{f.ic}</div>
              <div className="lp-card-t">{f.t}</div>
              <div className="lp-card-d">{f.d}</div>
            </div>
          ))}
        </div>
      </section>

      <section id="how" className="lp-how">
        <h2 className="lp-h2">Live in two minutes</h2>
        <div className="lp-steps">
          {STEPS.map((s) => (
            <div key={s.n} className="lp-step">
              <div className="lp-step-n">{s.n}</div>
              <div className="lp-step-t">{s.t}</div>
              <div className="lp-step-d">{s.d}</div>
            </div>
          ))}
        </div>
      </section>

      <section className="lp-compare">
        <h2 className="lp-h2">Why ProveKit</h2>
        <p className="lp-sub">Observability-tool depth, activation in one line — and it runs on your own infra.</p>
        <div className="lp-table-wrap">
          <table className="lp-table">
            <thead><tr><th>&nbsp;</th><th>Raw logs</th><th>Hosted SaaS tools</th><th>ProveKit</th></tr></thead>
            <tbody>
              {COMPARE.map((r) => (
                <tr key={r.f}>
                  <td>{r.f}</td>
                  <td className={cls(r.logs)}>{sym(r.logs)}</td>
                  <td className={cls(r.saas)}>{sym(r.saas)}</td>
                  <td className={cls(r.pk)}>{sym(r.pk)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="lp-quotes">
        <h2 className="lp-h2">Built for agent developers</h2>
        <div className="lp-quote-grid">
          {QUOTES.map((q) => (
            <div key={q.by} className="lp-quote">
              <div className="lp-quote-text">“{q.t}”</div>
              <div className="lp-quote-by">— {q.by}</div>
            </div>
          ))}
        </div>
      </section>

      <section id="faq" className="lp-faq">
        <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify({
          "@context": "https://schema.org", "@type": "FAQPage",
          mainEntity: FAQ.map((f) => ({ "@type": "Question", name: f.q,
            acceptedAnswer: { "@type": "Answer", text: f.a } })),
        }) }} />
        <h2 className="lp-h2">Questions</h2>
        <div className="lp-faq-grid">
          {FAQ.map((f) => (
            <div key={f.q} className="lp-faq-item">
              <div className="lp-faq-q">{f.q}</div>
              <div className="lp-faq-a">{f.a}</div>
            </div>
          ))}
        </div>
      </section>

      <section className="lp-final">
        <h2>Ship your first trace today.</h2>
        <p>Open source, self-hostable, and free to run. Bring your own keys, own your data.</p>
        <div className="lp-cta" style={{ justifyContent: "center" }}>
          <Link href={primary.href} className="btn lp-btn-primary">{primary.label}</Link>
          <GitHubStars />
        </div>
      </section>

      <footer className="lp-footer">
        <div className="lp-foot-brand">
          <div><span className="lp-logo">◇</span> Prove<b style={{ color: "var(--muted)", fontWeight: 600 }}>Kit</b></div>
          <div className="muted" style={{ fontSize: 12.5, marginTop: 6 }}>Drop-in agent tracing · evaluation · observability</div>
        </div>
        <div className="lp-foot-cols">
          {FOOTER.map((col) => (
            <div key={col.h} className="lp-foot-col">
              <div className="lp-foot-h">{col.h}</div>
              {col.links.map((l) => (
                l.href.startsWith("/")
                  ? <Link key={l.t} href={l.href}>{l.t}</Link>
                  : <a key={l.t} href={l.href} target="_blank" rel="noreferrer">{l.t}</a>
              ))}
            </div>
          ))}
        </div>
      </footer>
      <div className="lp-foot-legal">© {2026} ProveKit · Open source · MIT-style license</div>

      <LandingStyles />
    </div>
  );
}

function TracePreview() {
  // A styled mini "trace" — the product's signature nested flow, drawn in CSS.
  return (
    <div className="lp-preview" aria-hidden>
      <div className="lp-preview-bar">
        <span className="lp-dot r" /><span className="lp-dot y" /><span className="lp-dot g" />
        <span className="lp-preview-title">research-agent · 289ms · 1,904 tokens · ~$0.006</span>
      </div>
      <div className="lp-flow">
        {ROWS.map((r, i) => (
          <div key={i} className={`lp-row ${r.fail ? "fail" : ""}`} style={{ paddingLeft: 12 + r.d * 20 }}>
            <span className="lp-badge" data-t={r.type}>{r.type}</span>
            <span className="lp-row-label">{r.label}</span>
            <span className="lp-row-bar"><span className="lp-row-fill" style={{ width: r.w, background: `var(${BAR[r.type]})` }} /></span>
            <span className="lp-row-ms">{r.ms}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

const TYPE_C: Record<string, string> = { agent: "var(--accent)", llm: "var(--blue)", tool: "var(--purple)", step: "var(--muted)" };

function FlowVisual() {
  // A self-contained SVG agent-flow graph — the product's signature node view, with
  // animated directional edges (the selected path in accent, a failed exit in red).
  const W = 156, H = 42;
  const N: Record<string, { x: number; y: number; t: string; l: string }> = {
    a: { x: 12, y: 128, t: "agent", l: "orchestrator" },
    b: { x: 250, y: 26, t: "llm", l: "plan · gpt-4o" },
    c: { x: 250, y: 128, t: "tool", l: "retrieve" },
    d: { x: 486, y: 128, t: "step", l: "doc · 0.95" },
    e: { x: 250, y: 230, t: "llm", l: "synthesize" },
    f: { x: 486, y: 230, t: "tool", l: "fetch ✗" },
  };
  const E: { s: string; t: string; k?: "hot" | "fail" }[] = [
    { s: "a", t: "b" }, { s: "a", t: "c" }, { s: "c", t: "d" },
    { s: "a", t: "e", k: "hot" }, { s: "e", t: "f", k: "fail" },
  ];
  const path = (s: string, t: string) => {
    const A = N[s], B = N[t];
    const sx = A.x + W, sy = A.y + H / 2, tx = B.x, ty = B.y + H / 2, mx = sx + (tx - sx) / 2;
    return `M ${sx} ${sy} C ${mx} ${sy} ${mx} ${ty} ${tx} ${ty}`;
  };
  return (
    <div className="lp-flowbox">
      <svg viewBox="0 0 654 300" className="lp-flowsvg" role="img" aria-label="Agent flow graph">
        <defs>
          {[["def", "var(--border-strong)"], ["hot", "var(--accent)"], ["fail", "var(--red)"]].map(([id, c]) => (
            <marker key={id} id={`arw-${id}`} markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto">
              <path d="M0,0 L6,3 L0,6 Z" fill={c} />
            </marker>
          ))}
        </defs>
        {E.map((e, i) => (
          <path key={i} d={path(e.s, e.t)} fill="none" markerEnd={`url(#arw-${e.k || "def"})`}
            className={`lp-edge ${e.k === "hot" ? "hot" : ""} ${e.k === "fail" ? "fail" : ""}`} />
        ))}
        {Object.entries(N).map(([id, n]) => (
          <g key={id}>
            <title>{`${n.t} · ${n.l}`}</title>
            <rect x={n.x} y={n.y} width={W} height={H} rx={10} className={`lp-fnode ${id === "f" ? "fail" : ""}`}
              style={{ stroke: id === "f" ? "var(--red)" : TYPE_C[n.t] }} />
            <text x={n.x + 12} y={n.y + 26} className="lp-ftext">
              <tspan className="lp-ftag" style={{ fill: id === "f" ? "var(--red)" : TYPE_C[n.t] }}>{n.t.toUpperCase()}</tspan>
              <tspan dx="8" style={{ fill: id === "f" ? "var(--red)" : "var(--text)" }}>{n.l}</tspan>
            </text>
          </g>
        ))}
      </svg>
    </div>
  );
}

const BAR: Record<string, string> = { agent: "--accent", llm: "--blue", tool: "--purple", step: "--muted" };
const ROWS = [
  { type: "agent", label: "research-orchestrator", d: 0, w: "96%", ms: "289ms", fail: false },
  { type: "llm", label: "chat gpt-4o-mini", d: 1, w: "22%", ms: "13ms", fail: false },
  { type: "agent", label: "sub-agent: pricing", d: 1, w: "60%", ms: "67ms", fail: false },
  { type: "tool", label: "retrieve", d: 2, w: "18%", ms: "11ms", fail: false },
  { type: "step", label: "doc #0 · relevance 0.95", d: 3, w: "8%", ms: "4ms", fail: false },
  { type: "llm", label: "chat gpt-4o", d: 2, w: "30%", ms: "13ms", fail: false },
  { type: "tool", label: "fetch-attempt-1", d: 2, w: "14%", ms: "7ms", fail: true },
  { type: "tool", label: "fetch-attempt-2", d: 2, w: "12%", ms: "6ms", fail: false },
  { type: "llm", label: "synthesize · claude-sonnet-5", d: 1, w: "40%", ms: "12ms", fail: false },
];

const FEATURES = [
  { ic: "◇", c: "var(--accent)", t: "Drop-in tracing", d: "One import auto-captures OpenAI, Anthropic, LangChain, LlamaIndex, CrewAI, and outbound HTTP — no per-call code." },
  { ic: "❖", c: "var(--blue)", t: "Flow graph & waterfall", d: "See the run as an animated node graph or a time-proportional waterfall — inputs, outputs, tokens, cost, and logs per span." },
  { ic: "▶", c: "var(--accent)", t: "Interactive debugging", d: "Don't just read logs — edit any captured LLM call's prompt or variables and re-run it with real data, diff the output, or replay the whole trace live from a step." },
  { ic: "✓", c: "var(--green)", t: "Evaluation & CI gates", d: "Build datasets from real traces, score with built-in, LLM-judge, or custom scorers, and fail your build on a regression with pk.evaluate()." },
  { ic: "▲", c: "var(--amber)", t: "Dashboards & alerts", d: "Volume, error rate, latency p50/p95, tokens, and cost over time — with threshold alerts that email on a breach." },
  { ic: "⌘", c: "var(--purple)", t: "Debug over MCP", d: "Point Claude Desktop or Cursor at your project key and let an agent query and reason over your traces — no extra client code." },
  { ic: "⊞", c: "var(--accent)", t: "Multi-project & self-host", d: "Isolated projects with members and roles, per-project keys, PII redaction, retention — all on your own infra via Docker." },
];

const STEPS = [
  { n: "1", t: "Create a project", d: "Sign in and grab a project key — one per app or environment." },
  { n: "2", t: "Add the SDK", d: "pip install, drop the key in .env, add one import at your entrypoint." },
  { n: "3", t: "Review the flow", d: "Every run streams to the portal — inspect, evaluate, and monitor it." },
];

const FAQ = [
  { q: "Which frameworks does it support?", a: "OpenAI, Anthropic, LangChain, LlamaIndex, CrewAI and more are auto-captured; anything OpenTelemetry-instrumented nests too. Custom steps take one line." },
  { q: "Do I have to send my data anywhere?", a: "No. ProveKit is self-hostable — run it on your own infra with Docker, bring your own model keys, and your traces never leave your environment." },
  { q: "Is it really just one line?", a: "Yes for capture: import provekit.auto turns on tracing for the libraries you already use. Add @pk.trace to group a run, and pk.span()/pk.score() where you want more detail." },
  { q: "How does the CI gate work?", a: "pk.evaluate() runs a target over a dataset, scores each output, and returns a summary — assert on mean_score to fail the build on a regression." },
  { q: "What does it cost?", a: "The project is open source and free to run. You only pay for your own infra and model usage." },
  { q: "Is there vendor lock-in?", a: "No. It's OpenTelemetry-native and open source — one SDK, standard formats, and you own the deployment." },
];

type Cell = "yes" | "no" | "partial" | string;
const sym = (v: Cell) => (v === "yes" ? "✓" : v === "no" ? "—" : v === "partial" ? "◐" : v);
const cls = (v: Cell) => (v === "yes" ? "yes" : v === "no" ? "no" : "");

const COMPARE: { f: string; logs: Cell; saas: Cell; pk: Cell }[] = [
  { f: "Nested flow graph", logs: "no", saas: "yes", pk: "yes" },
  { f: "One-line setup", logs: "no", saas: "partial", pk: "yes" },
  { f: "Evaluation + CI gate", logs: "no", saas: "yes", pk: "yes" },
  { f: "Dashboards + alerts", logs: "partial", saas: "yes", pk: "yes" },
  { f: "Self-host, your data", logs: "yes", saas: "no", pk: "yes" },
  { f: "Open source", logs: "yes", saas: "no", pk: "yes" },
  { f: "Debug over MCP", logs: "no", saas: "no", pk: "yes" },
];

const QUOTES = [
  { t: "It took one import to see the whole agent run — the failed tool call was obvious in seconds.", by: "AI engineer, early user" },
  { t: "Finally an eval gate we can actually put in CI. A bad prompt change goes red before it ships.", by: "Platform team lead" },
  { t: "Self-hosted, our keys, our data. That's the part that got it approved.", by: "Staff engineer" },
];

const FOOTER = [
  { h: "Product", links: [{ t: "Features", href: "/#features" }, { t: "Agent flow", href: "/#flow" }, { t: "Dashboard", href: "/dashboard" }, { t: "Pricing", href: "/#faq" }] },
  { h: "Resources", links: [{ t: "Blog", href: "/blog" }, { t: "Docs", href: "https://github.com/MobirizerServices/ProveKit/tree/main/docs" }, { t: "Changelog", href: "https://github.com/MobirizerServices/ProveKit/blob/main/CHANGELOG.md" }] },
  { h: "Community", links: [{ t: "Community", href: "/community" }, { t: "GitHub", href: "https://github.com/MobirizerServices/ProveKit" }, { t: "Discussions", href: "https://github.com/MobirizerServices/ProveKit/discussions" }] },
  { h: "Legal", links: [{ t: "Privacy", href: "/privacy" }, { t: "Terms", href: "/terms" }, { t: "Security", href: "https://github.com/MobirizerServices/ProveKit/blob/main/SECURITY.md" }] },
];

function LandingStyles() {
  return (
    <style jsx global>{`
      .lp { max-width: 1120px; margin: 0 auto; padding: 0 22px 60px; }
      .lp a { color: inherit; text-decoration: none; }
      .lp-nav { display: flex; align-items: center; justify-content: space-between; padding: 20px 2px; position: sticky; top: 0; background: color-mix(in srgb, var(--bg) 82%, transparent); backdrop-filter: blur(8px); z-index: 30; }
      .lp-brand { font-weight: 600; font-size: 15px; } .lp-brand b { color: var(--muted); font-weight: 600; }
      .lp-logo { color: var(--accent); }
      .lp-navlinks { display: flex; align-items: center; gap: 22px; font-size: 13.5px; color: var(--muted); }
      .lp-navlinks a:hover { color: var(--text); }
      .lp-signin { padding: 7px 14px; border: 1px solid var(--border-strong); border-radius: 8px; color: var(--text) !important; }
      .lp-signin:hover { background: var(--panel-2); }
      .lp-navdesktop { display: contents; }
      .lp-burger { display: none; background: transparent; border: none; color: var(--text); font-size: 18px; cursor: pointer; padding: 4px 8px; }
      .lp-mobilemenu { display: none; }
      @media (max-width: 820px) {
        .lp-navdesktop { display: none; }
        .lp-burger { display: block; }
        .lp-mobilemenu { display: flex; flex-direction: column; gap: 4px; padding: 10px 22px 16px; border-bottom: 1px solid var(--border); position: sticky; top: 60px; background: var(--bg); z-index: 29; }
        .lp-mobilemenu a { padding: 9px 6px; color: var(--muted); font-size: 15px; }
        .lp-mobilemenu a:hover { color: var(--text); }
      }

      .lp-hero { display: grid; grid-template-columns: 1.05fr 1fr; gap: 40px; align-items: center; padding: 54px 0 40px; position: relative; }
      .lp-hero::before { content: ""; position: absolute; inset: -80px -200px auto; height: 360px; z-index: -1;
        background: radial-gradient(closest-side, color-mix(in srgb, var(--accent) 16%, transparent), transparent),
                    radial-gradient(closest-side, color-mix(in srgb, var(--blue) 12%, transparent), transparent);
        background-position: 20% 0, 80% 20%; background-size: 60% 100%, 55% 90%; background-repeat: no-repeat; filter: blur(10px); }
      .lp-pill { display: inline-block; font-size: 12px; color: var(--muted); border: 1px solid var(--border-strong); border-radius: 999px; padding: 5px 12px; margin-bottom: 18px; }
      .lp-hero h1 { font-size: 46px; line-height: 1.07; letter-spacing: -1.5px; margin: 0; }
      .lp-hero-copy p { font-size: 16.5px; color: var(--muted); line-height: 1.55; margin: 18px 0 26px; max-width: 520px; }
      .lp-hero-copy b { color: var(--text); }
      .lp-cta { display: flex; gap: 12px; flex-wrap: wrap; }
      .lp-btn, .lp-btn-primary { padding: 12px 22px !important; font-size: 15px !important; }
      .lp-btn-primary { background: var(--accent); color: #08120b; font-weight: 600; }
      .lp-btn-primary:hover { filter: brightness(1.06); }
      .lp-trust { display: flex; gap: 18px; flex-wrap: wrap; margin-top: 26px; font-size: 12.5px; color: var(--faint); }
      .lp-whofor { margin: 14px 0 0; font-size: 13px; color: var(--muted); }
      .lp-fnode { cursor: default; }

      .lp-preview { border: 1px solid var(--border-strong); border-radius: 14px; overflow: hidden; background: var(--panel); box-shadow: var(--sh-2); }
      .lp-preview-bar { display: flex; align-items: center; gap: 6px; padding: 10px 14px; border-bottom: 1px solid var(--border); background: var(--bg-2); }
      .lp-dot { width: 9px; height: 9px; border-radius: 999px; } .lp-dot.r { background: #ff5f57; } .lp-dot.y { background: #febc2e; } .lp-dot.g { background: #28c840; }
      .lp-preview-title { font-size: 11.5px; color: var(--muted); margin-left: 8px; font-family: var(--font-mono); }
      .lp-flow { padding: 10px 12px; display: flex; flex-direction: column; gap: 5px; }
      .lp-row { display: flex; align-items: center; gap: 9px; font-size: 12px; }
      .lp-row.fail .lp-row-label { color: var(--red); }
      .lp-badge { font-size: 8.5px; font-weight: 700; text-transform: uppercase; letter-spacing: .3px; padding: 1px 5px; border-radius: 4px; border: 1px solid; }
      .lp-badge[data-t=agent] { color: var(--accent); border-color: var(--accent); }
      .lp-badge[data-t=llm] { color: var(--blue); border-color: var(--blue); }
      .lp-badge[data-t=tool] { color: var(--purple); border-color: var(--purple); }
      .lp-badge[data-t=step] { color: var(--muted); border-color: var(--border-strong); }
      .lp-row-label { flex: 0 0 40%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
      .lp-row-bar { flex: 1; height: 8px; background: var(--bg-2); border-radius: 4px; overflow: hidden; }
      .lp-row-fill { display: block; height: 100%; border-radius: 4px; opacity: .85; }
      .lp-row.fail .lp-row-fill { background: var(--red) !important; }
      .lp-row-ms { flex: 0 0 42px; text-align: right; color: var(--muted); font-size: 10.5px; }

      .lp-code-band { display: grid; grid-template-columns: 1fr 1.1fr; gap: 34px; align-items: center; padding: 44px 0; border-top: 1px solid var(--border); }
      .lp-code-band h2 { font-size: 26px; letter-spacing: -0.6px; margin: 0 0 12px; }
      .lp-code-copy p { color: var(--muted); font-size: 15px; line-height: 1.55; }
      .lp-check { list-style: none; padding: 0; margin: 16px 0 0; }
      .lp-check li { position: relative; padding-left: 22px; margin: 9px 0; font-size: 14px; color: var(--text); }
      .lp-check li::before { content: "✓"; position: absolute; left: 0; color: var(--green); font-weight: 700; }
      .lp-code { margin: 0; padding: 18px; border-radius: 12px; background: var(--panel); border: 1px solid var(--border-strong); font-size: 12.5px; line-height: 1.6; font-family: var(--font-mono); overflow-x: auto; white-space: pre; box-shadow: var(--sh-1); }

      .lp-flowsec { padding: 50px 0; border-top: 1px solid var(--border); }
      .lp-flowbox { margin: 30px auto 0; max-width: 720px; border: 1px solid var(--border-strong); border-radius: 16px; background:
        radial-gradient(120% 100% at 50% 0, color-mix(in srgb, var(--accent) 7%, transparent), transparent 60%), var(--panel);
        padding: 18px; box-shadow: var(--sh-2); }
      .lp-flowsvg { width: 100%; height: auto; display: block; }
      .lp-fnode { fill: var(--panel-2); stroke-width: 1.4; }
      .lp-fnode.fail { fill: color-mix(in srgb, var(--red) 8%, var(--panel-2)); }
      .lp-ftext { font-family: var(--font-mono); font-size: 12.5px; }
      .lp-ftag { font-size: 9px; font-weight: 700; letter-spacing: .4px; }
      .lp-edge { stroke: var(--border-strong); stroke-width: 1.6; stroke-dasharray: 6 5; animation: rf-flow .6s linear infinite; }
      .lp-edge.hot { stroke: var(--accent); stroke-width: 2.2; }
      .lp-edge.fail { stroke: var(--red); stroke-width: 2; }
      @keyframes rf-flow { to { stroke-dashoffset: -11; } }
      @media (prefers-reduced-motion: reduce) { .lp-edge { animation: none; } }

      .lp-demo { padding: 50px 0; border-top: 1px solid var(--border); text-align: center; }
      .lp-demo-frame { max-width: 860px; margin: 30px auto 0; border: 1px solid var(--border-strong); border-radius: 14px; overflow: hidden; box-shadow: var(--sh-2); background: var(--panel); }
      .lp-demo-bar { display: flex; gap: 6px; padding: 10px 14px; border-bottom: 1px solid var(--border); background: var(--bg-2); }
      .lp-demo-img { display: block; width: 100%; height: auto; }

      .lp-compare { padding: 50px 0; border-top: 1px solid var(--border); }
      .lp-table-wrap { overflow-x: auto; max-width: 820px; margin: 30px auto 0; }
      .lp-table { width: 100%; border-collapse: collapse; font-size: 14px; }
      .lp-table th, .lp-table td { padding: 12px 14px; text-align: left; border-bottom: 1px solid var(--border); }
      .lp-table th { color: var(--muted); font-weight: 500; font-size: 12.5px; }
      .lp-table td:first-child { color: var(--muted); }
      .lp-table .yes { color: var(--green); font-weight: 600; }
      .lp-table .no { color: var(--faint); }

      .lp-quotes { padding: 50px 0; border-top: 1px solid var(--border); }
      .lp-quote-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; margin-top: 30px; }
      .lp-quote { background: var(--panel); border: 1px solid var(--border); border-radius: 14px; padding: 20px; }
      .lp-quote-text { font-size: 14.5px; line-height: 1.55; }
      .lp-quote-by { margin-top: 14px; font-size: 12.5px; color: var(--muted); }

      .lp-features, .lp-how { padding: 50px 0; border-top: 1px solid var(--border); }
      .lp-h2 { font-size: 30px; letter-spacing: -0.8px; text-align: center; margin: 0; }
      .lp-sub { text-align: center; color: var(--muted); font-size: 15px; margin: 12px 0 34px; }
      .lp-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; }
      .lp-card { background: var(--panel); border: 1px solid var(--border); border-radius: 14px; padding: 20px; transition: border-color .15s, transform .15s; }
      .lp-card:hover { border-color: var(--border-strong); transform: translateY(-2px); }
      .lp-card-ic { font-size: 22px; }
      .lp-card-t { font-weight: 600; font-size: 15.5px; margin: 12px 0 6px; }
      .lp-card-d { color: var(--muted); font-size: 13.5px; line-height: 1.5; }

      .lp-steps { display: grid; grid-template-columns: repeat(3, 1fr); gap: 20px; max-width: 820px; margin: 34px auto 0; }
      .lp-step-n { width: 30px; height: 30px; border-radius: 999px; display: grid; place-items: center; background: var(--accent-soft); color: var(--accent); font-weight: 700; font-size: 14px; }
      .lp-step-t { font-weight: 600; font-size: 15.5px; margin: 12px 0 5px; }
      .lp-step-d { color: var(--muted); font-size: 13.5px; line-height: 1.5; }

      .lp-logos { padding: 30px 0 6px; text-align: center; }
      .lp-logos-label { font-size: 12px; text-transform: uppercase; letter-spacing: 1px; color: var(--faint); margin-bottom: 16px; }
      .lp-logos-row { display: flex; flex-wrap: wrap; gap: 10px 12px; justify-content: center; }
      .lp-logo-chip { font-size: 14px; color: var(--muted); border: 1px solid var(--border); border-radius: 999px; padding: 7px 16px; }

      .lp-faq { padding: 50px 0; border-top: 1px solid var(--border); }
      .lp-faq-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px 28px; max-width: 900px; margin: 30px auto 0; }
      .lp-faq-q { font-weight: 600; font-size: 15px; margin-bottom: 5px; }
      .lp-faq-a { color: var(--muted); font-size: 14px; line-height: 1.55; }

      .lp-final { text-align: center; padding: 60px 0 40px; border-top: 1px solid var(--border); }
      .lp-final h2 { font-size: 32px; letter-spacing: -0.8px; margin: 0 0 10px; }
      .lp-final p { color: var(--muted); font-size: 15.5px; margin: 0 0 26px; }
      .lp-footer { display: flex; justify-content: space-between; gap: 40px; padding: 34px 0 20px; border-top: 1px solid var(--border); flex-wrap: wrap; }
      .lp-foot-brand { font-weight: 600; font-size: 15px; }
      .lp-foot-cols { display: flex; gap: 48px; flex-wrap: wrap; }
      .lp-foot-col { display: flex; flex-direction: column; gap: 9px; }
      .lp-foot-h { font-size: 12px; text-transform: uppercase; letter-spacing: 0.6px; color: var(--faint); margin-bottom: 3px; }
      .lp-foot-col a { font-size: 13.5px; color: var(--muted); }
      .lp-foot-col a:hover { color: var(--text); }
      .lp-foot-legal { padding: 16px 0 10px; border-top: 1px solid var(--border); font-size: 12.5px; color: var(--faint); text-align: center; }

      @media (max-width: 820px) {
        .lp-hero, .lp-code-band { grid-template-columns: 1fr; }
        .lp-grid, .lp-steps, .lp-faq-grid, .lp-quote-grid { grid-template-columns: 1fr; }
        .lp-hero h1 { font-size: 36px; }
        .lp-navlinks .lp-hidemobile { display: none; }
        .lp-footer { gap: 24px; }
      }
    `}</style>
  );
}
