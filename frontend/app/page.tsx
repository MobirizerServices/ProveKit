"use client";

import { useEffect, useState } from "react";
import s from "./page.module.css";

const GITHUB = "https://github.com/MobirizerServices/ProveKit";
const DOCS = `${GITHUB}/blob/main/docs/README.md`;

const INSTALLS: Record<string, string> = {
  pipx: "pipx install provekit",
  pip: "pip install provekit",
  uvx: "uvx provekit",
  docker: "docker run ghcr.io/mobirizerservices/provekit",
};

// The loop, as ProveKit actually prints it. Revealed line-by-line below.
const TERM: { t: string; c: string; d: number }[] = [
  { t: "$ provekit run .provekit/tests/", c: "p", d: 60 },
  { t: "→ connect  mcp://localhost:8931", c: "dim", d: 500 },
  { t: '→ stream   "Sure — let me pull up your order and check the refund window…"', c: "stream", d: 900 },
  { t: "+ assert   tool_called(\"lookup_order\")            ✓", c: "assert", d: 380 },
  { t: "+ assert   latency < 2000ms            (1180ms)   ✓", c: "assert", d: 380 },
  { t: "+ assert   contains(\"refund\")                     ✓", c: "assert", d: 380 },
  { t: "✓ passed · 3/3 assertions · 1.18s · $0.0004", c: "pass", d: 1600 },
];

function CopyButton({ text }: { text: string }) {
  const [done, setDone] = useState(false);
  return (
    <button
      className={s.copyBtn}
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text);
          setDone(true);
          setTimeout(() => setDone(false), 1400);
        } catch {
          /* clipboard blocked — no-op */
        }
      }}
      aria-label="Copy command"
    >
      {done ? "copied ✓" : "copy"}
    </button>
  );
}

function Terminal() {
  const [shown, setShown] = useState(0);
  const [reduce, setReduce] = useState(false);
  useEffect(() => {
    setReduce(window.matchMedia("(prefers-reduced-motion: reduce)").matches);
  }, []);
  useEffect(() => {
    // Respect reduced motion: show the whole run at once, no typing loop.
    if (reduce) {
      setShown(TERM.length);
      return;
    }
    if (shown >= TERM.length) {
      const r = setTimeout(() => setShown(0), 2600); // loop
      return () => clearTimeout(r);
    }
    const t = setTimeout(() => setShown((n) => n + 1), TERM[shown].d);
    return () => clearTimeout(t);
  }, [shown, reduce]);
  return (
    <div className={s.term}>
      <div className={s.termHead}>
        <span className={s.tdot} style={{ background: "#ef6a5b" }} />
        <span className={s.tdot} style={{ background: "#e5b24a" }} />
        <span className={s.tdot} style={{ background: "#3ddc84" }} />
        <span className={s.tname}>provekit — run → assert → ✓ passed</span>
      </div>
      <div className={s.termBody}>
        {TERM.slice(0, shown).map((l, i) => (
          <div key={i} className={`${s.ln} ${s[l.c]}`}>
            {l.t}
            {i === shown - 1 && shown < TERM.length ? <span className={s.caret}>.</span> : null}
          </div>
        ))}
      </div>
    </div>
  );
}

function Quickstart() {
  const [tab, setTab] = useState("pipx");
  return (
    <div className={s.qs}>
      <div>
        <div className={s.tabs}>
          {Object.keys(INSTALLS).map((k) => (
            <button key={k} className={`${s.tab} ${tab === k ? s.active : ""}`} onClick={() => setTab(k)}>
              {k}
            </button>
          ))}
        </div>
        <div className={s.codeBox}>
          <span>
            <span style={{ color: "var(--faint)" }}>$ </span>
            {INSTALLS[tab]}
          </span>
          <CopyButton text={INSTALLS[tab]} />
        </div>
        <div className={s.codeBox} style={{ marginTop: 10 }}>
          <span>
            <span style={{ color: "var(--faint)" }}>$ </span>provekit run .provekit/tests/
          </span>
          <CopyButton text="provekit run .provekit/tests/" />
        </div>
      </div>
      <ol className={s.qsList}>
        <li><span><b>Install</b> — one command, no SDK, nothing to import into your code.</span></li>
        <li><span><b>Connect</b> — point it at an LLM API, MCP server, HTTP or A2A agent.</span></li>
        <li><span><b>Run</b> — watch it stream live; every call, tool, latency and cost is captured.</span></li>
        <li><span><b>Assert</b> — click <code>+ contains</code> on a result and it saves a plain-text, git-diffable test.</span></li>
        <li><span><b>Ship</b> — <code>provekit run .provekit/tests/</code> in CI; no green check, no merge.</span></li>
      </ol>
    </div>
  );
}

const FEATURES = [
  ["◇", "Any protocol", "LLM APIs, MCP servers, HTTP agents, A2A — one client, no per-provider SDK."],
  ["≋", "Streaming-first", "See live tokens and every tool call as they happen, not just the final answer."],
  ["✓", "Assertions", "Check content, tool-use, latency, cost or JSON shape — the checks agents actually need."],
  ["⟲", "Snapshot & regress", "Freeze a good run; diff every future run against it so a tweak can't silently break prod."],
  ["⚙", "CI-native", "Exit codes and machine-readable output. One workflow file gates every agent PR."],
  ["$", "Cost & latency", "Every run records tokens, latency and spend — the numbers your team asks for."],
  ["⇄", "Multi-provider", "Same run, swap the model, compare outputs side by side."],
  ["⌘", "Connections", "Save endpoints, attach auth once, reuse across every run."],
  ["🔒", "Local-first", "Runs on your machine. Your keys and prompts never leave it."],
];

const CASES = [
  "Test an MCP server before you ship it.",
  "Regression-test a prompt change so a tweak can't break prod.",
  "Gate agent PRs in CI — no merge unless the suite is green.",
  "Debug a flaky agent by replaying the exact run that failed.",
  "Compare two providers on the same task, side by side.",
  "Eval before deploy — a scorecard your team actually trusts.",
];

export default function Landing() {
  const [scrolled, setScrolled] = useState(false);
  const [stars, setStars] = useState<number | null>(null);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 460);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  useEffect(() => {
    // Real star count — falls back silently to "★ GitHub" if rate-limited/offline.
    fetch("https://api.github.com/repos/MobirizerServices/ProveKit")
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        if (d && typeof d.stargazers_count === "number") setStars(d.stargazers_count);
      })
      .catch(() => {});
  }, []);

  const starLabel =
    stars == null ? "★ GitHub" : `★ ${stars >= 1000 ? (stars / 1000).toFixed(1) + "k" : stars}`;

  return (
    <div className={s.page}>
      <a className={s.skip} href="#main">Skip to content</a>
      {/* nav */}
      <nav className={s.nav}>
        <div className={s.navInner}>
          <a className={s.brand} href="/"><span className={s.dia}>◇</span> ProveKit</a>
          <div className={s.navLinks}>
            <a href="#how">How it works</a>
            <a href="#features">Features</a>
            <a href="#compare">Why ProveKit</a>
            <a href={DOCS}>Docs</a>
          </div>
          <div className={s.navRight}>
            {scrolled && (
              <div className={s.installMini}>
                <span className={s.dollar}>$</span>
                <span className={s.cmd}>pipx install provekit</span>
                <CopyButton text="pipx install provekit" />
              </div>
            )}
            <a className={s.btnGhost} href={GITHUB}>{starLabel}</a>
            <a className={s.btnGold} href="/console">Open app</a>
          </div>
        </div>
      </nav>

      {/* hero */}
      <header className={s.hero} id="main">
        <div className={s.wrap}>
          <span className={s.eyebrow}>◇ Open-source universal agent client</span>
          <h1 className={s.h1}>Prove any AI agent works.</h1>
          <p className={s.sub}>
            Test, debug and evaluate any agent — <b>LLM · MCP · HTTP · A2A</b>, any provider, <b>no SDK</b>.
            Run it with live streaming, turn a run into a regression test in one click, and run the suite in CI.
          </p>
          <div className={s.heroCtas}>
            <div className={s.install}>
              <span className={s.dollar}>$</span>
              <span className={s.cmd}>pipx install provekit</span>
              <CopyButton text="pipx install provekit" />
            </div>
            <a className={s.btnGhost} href={GITHUB}>★ Star on GitHub</a>
            <a className={s.btnGold} href={DOCS}>Read the docs →</a>
          </div>
          <div className={s.heroBadges}>
            <span className={s.b}><span className={s.dot} /> Open source · MIT</span>
            <span className={s.b}><span className={s.dot} /> Python 3.13</span>
            <span className={s.b}><span className={s.dot} /> Runs locally — your keys never leave your machine</span>
          </div>
          <Terminal />
        </div>
      </header>

      {/* protocol strip */}
      <section className={s.section} style={{ paddingTop: 40, paddingBottom: 40 }}>
        <div className={s.wrap}>
          <span className={s.kicker}>Point it at anything</span>
          <div className={s.strip}>
            <span className={s.proto}><b>LLM</b> — OpenAI, Anthropic, any chat API</span>
            <span className={s.proto}><b>MCP</b> — Model Context Protocol servers</span>
            <span className={s.proto}><b>HTTP</b> — your own agent endpoint</span>
            <span className={s.proto}><b>A2A</b> — agent-to-agent</span>
          </div>
        </div>
      </section>

      {/* how it works */}
      <section className={s.section} id="how">
        <div className={s.wrap}>
          <span className={s.kicker}>How it works</span>
          <h2 className={s.h2}>Connect → Run → Assert → Regress in CI</h2>
          <p className={s.lead}>The whole loop is fifteen seconds. Grasp it once and you never write agent-test glue again.</p>
          <div className={s.steps}>
            {[
              ["01", "Connect", "Point ProveKit at any endpoint — an LLM API, an MCP server, an HTTP or A2A agent. No SDK to import."],
              ["02", "Run", "Fire a request and watch it stream. Every token, tool call, latency and cost is captured as a run."],
              ["03", "Assert", "Add checks to a good run — content, tools, latency, cost — and save it as a regression test."],
              ["04", "Regress", "Drop the suite into CI. Exit codes and JUnit output mean a broken agent can't merge."],
            ].map(([n, h, p]) => (
              <div className={s.step} key={n}>
                <div className={s.num}>{n}</div>
                <h3>{h}</h3>
                <p>{p}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* features */}
      <section className={s.section} id="features">
        <div className={s.wrap}>
          <span className={s.kicker}>Features</span>
          <h2 className={s.h2}>Everything a testing tool needs — and nothing an SDK forces on you.</h2>
          <div className={s.features}>
            {FEATURES.map(([i, h, p]) => (
              <div className={s.feat} key={h}>
                <div className={s.fi}>{i}</div>
                <h3>{h}</h3>
                <p>{p}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* comparison */}
      <section className={s.section} id="compare">
        <div className={s.wrap}>
          <span className={s.kicker}>Why ProveKit</span>
          <h2 className={s.h2}>You&rsquo;re already testing agents somehow. Here&rsquo;s the honest comparison.</h2>
          <div className={s.cmp}>
            <table>
              <thead>
                <tr>
                  <th></th>
                  <th className={s.pkcol}>◇ ProveKit</th>
                  <th>SDK scripts</th>
                  <th>Postman</th>
                  <th>Hosted eval SaaS</th>
                </tr>
              </thead>
              <tbody>
                {[
                  ["Any protocol (LLM/MCP/HTTP/A2A)", "yes", "no", "no", "some"],
                  ["Live streaming + tool calls", "yes", "some", "no", "some"],
                  ["Run → regression test", "yes", "no", "no", "yes"],
                  ["CI-native (exit codes, JUnit)", "yes", "some", "no", "some"],
                  ["Runs locally, keys never leave", "yes", "yes", "yes", "no"],
                  ["Open source · no seat pricing", "yes", "yes", "some", "no"],
                ].map((row) => (
                  <tr key={row[0]}>
                    <td>{row[0]}</td>
                    {row.slice(1).map((v, i) => (
                      <td key={i} className={v === "yes" ? s.yes : v === "no" ? s.no : ""}>
                        {v === "yes" ? "✓" : v === "no" ? "—" : "~"}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className={s.footNote}>
            Not the right fit if you want a fully-managed SaaS dashboard with a team seat model — ProveKit is
            deliberately local-first and open source.
          </p>
        </div>
      </section>

      {/* quickstart */}
      <section className={s.section}>
        <div className={s.wrap}>
          <span className={s.kicker}>Quickstart</span>
          <h2 className={s.h2}>From install to your first ✓ passed in under a minute.</h2>
          <Quickstart />
        </div>
      </section>

      {/* use cases */}
      <section className={s.section}>
        <div className={s.wrap}>
          <span className={s.kicker}>Use cases</span>
          <h2 className={s.h2}>Find your job.</h2>
          <div className={s.cases}>
            {CASES.map((c) => (
              <div className={s.case} key={c}><span className={s.ci}>✓</span>{c}</div>
            ))}
          </div>
        </div>
      </section>

      {/* trust */}
      <section className={s.section}>
        <div className={s.wrap}>
          <span className={s.kicker}>Trust</span>
          <h2 className={s.h2}>Built for a tool that holds your API keys.</h2>
          <div className={s.trust}>
            {[
              ["🔒", "Local-first", "Everything runs on your machine. Your keys and prompts never leave it."],
              ["◇", "MIT licensed", "Permissive, forkable, no strings. Read every line."],
              ["⊘", "No telemetry", "No phone-home. Nothing about your agents is collected."],
              ["⇩", "Self-hostable", "Run it fully offline against a local model if you want."],
            ].map(([k, h, p]) => (
              <div className={s.tItem} key={h}>
                <span className={s.tk}>{k}</span>
                <div><h3>{h}</h3><p>{p}</p></div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* final cta */}
      <section className={s.finalCta}>
        <div className={s.wrap}>
          <h2 className={s.h2} style={{ marginInline: "auto" }}>Prove your agent works.</h2>
          <p className={s.lead} style={{ marginInline: "auto" }}>One command. No signup. No SDK.</p>
          <div style={{ display: "flex", justifyContent: "center" }}>
            <div className={s.install}>
              <span className={s.dollar}>$</span>
              <span className={s.cmd}>pipx install provekit</span>
              <CopyButton text="pipx install provekit" />
            </div>
          </div>
          <div style={{ display: "flex", gap: 12, justifyContent: "center", marginTop: 18 }}>
            <a className={s.btnGhost} href={GITHUB}>★ Star on GitHub</a>
            <a className={s.btnGold} href={DOCS}>Read the docs →</a>
          </div>
        </div>
      </section>

      {/* footer */}
      <footer className={s.footer}>
        <div className={s.wrap}>
          <div className={s.footCols}>
            <div>
              <a className={s.brand} href="/" style={{ marginBottom: 4 }}><span className={s.dia}>◇</span> ProveKit</a>
              <span style={{ color: "var(--faint)" }}>The open-source universal agent client.</span>
            </div>
            <div>
              <span className={s.ft}>Product</span>
              <a href="/console">Open app</a>
              <a href="#features">Features</a>
              <a href="#compare">Why ProveKit</a>
            </div>
            <div>
              <span className={s.ft}>Develop</span>
              <a href={DOCS}>Docs</a>
              <a href={GITHUB}>GitHub</a>
              <a href={`${GITHUB}/blob/main/CONTRIBUTING.md`}>Contributing</a>
            </div>
            <div>
              <span className={s.ft}>Trust</span>
              <a href={`${GITHUB}/blob/main/SECURITY.md`}>Security</a>
              <a href={`${GITHUB}/blob/main/LICENSE`}>MIT license</a>
            </div>
          </div>
          <div className={s.footNote}>◇ ProveKit · MIT · Python 3.13 · Next.js 14 · runs locally, your keys never leave your machine.</div>
        </div>
      </footer>
    </div>
  );
}
