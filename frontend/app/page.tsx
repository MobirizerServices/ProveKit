"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";

const DOCS = "https://github.com/MobirizerServices/ProveKit/tree/main/docs";
const REPO = "https://github.com/MobirizerServices/ProveKit";

export default function Landing() {
  const [authed, setAuthed] = useState(false);
  const [menu, setMenu] = useState(false);
  const [banner, setBanner] = useState(true);
  const [faq, setFaq] = useState(0);

  useEffect(() => { api.me().then(() => setAuthed(true)).catch(() => {}); }, []);
  useReveal();

  // Signed-in visitors get sent into the workspace instead of the signup flow.
  const start = authed ? "/traces" : "/signup";
  const startLabel = authed ? "Open workspace" : "Start tracing free";

  const ld = {
    "@context": "https://schema.org", "@type": "SoftwareApplication",
    name: "ProveKit", applicationCategory: "DeveloperApplication", operatingSystem: "Any",
    description: "Design, trace, replay, and evaluate every agent decision in one reliability workspace.",
    offers: { "@type": "Offer", price: "0", priceCurrency: "USD" }, url: REPO,
  };

  return (
    <div className="pk">
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(ld) }} />

      {/* ─────────────────────────── Header ─────────────────────────── */}
      <header className="pk-header">
        <div className="pk-header-in">
          <Link href="/" className="pk-wordmark"><Mark />PROVEKIT</Link>
          <nav className="pk-nav">
            <a href="#product">Product</a>
            <Link href="/traces">Live sandbox</Link>
            <a href="#teams">Solutions</a>
            <a href="#pricing">Pricing</a>
            <a href={DOCS} target="_blank" rel="noreferrer">Docs</a>
            <a href="#trust">Trust center</a>
          </nav>
          <div className="pk-header-cta">
            <Link href={authed ? "/traces" : "/login"} className="pk-signin">{authed ? "Workspace" : "Sign in"}</Link>
            <Link href={start} className="pk-start">Start tracing <Arrow /></Link>
          </div>
          <button className="pk-burger" aria-label="Menu" aria-expanded={menu} onClick={() => setMenu((o) => !o)}>
            {menu ? "✕" : "☰"}
          </button>
        </div>
      </header>
      {menu && (
        <div className="pk-mobile" onClick={() => setMenu(false)}>
          <a href="#product">Product</a>
          <Link href="/traces">Live sandbox</Link>
          <a href="#teams">Solutions</a>
          <a href="#pricing">Pricing</a>
          <a href={DOCS} target="_blank" rel="noreferrer">Docs</a>
          <a href="#trust">Trust center</a>
          <Link href={authed ? "/traces" : "/login"}>{authed ? "Workspace" : "Sign in"}</Link>
          <Link href={start}>{startLabel}</Link>
        </div>
      )}

      {/* ───────────────────── Announcement banner ──────────────────── */}
      {banner && (
        <div className="pk-announce">
          <div className="pk-announce-in">
            <span className="pk-announce-tag">✦ New release</span>
            <span>
              <b>Replay comparisons are now live.</b>{" "}
              <span className="pk-announce-dim">Change the agent. Keep the evidence.</span>
            </span>
            <a href="#replay">See deterministic replay <Arrow /></a>
          </div>
          <button className="pk-announce-x" aria-label="Dismiss announcement" onClick={() => setBanner(false)}>⊗</button>
        </div>
      )}

      {/* ───────────────────────────  Hero  ─────────────────────────── */}
      <section className="pk-hero">
        <div className="pk-hero-in">
          <div>
            <div className="pk-hero-kicker">
              <span className="pk-kicker-tag"><i className="pk-dot" />AI reliability workspace</span>
              <span>Trace → Replay → Evaluate</span>
            </div>
            <div className="pk-hero-eyebrow"><i />The evidence layer for production AI</div>
            <h1>
              Build agents.<br />
              <span className="pk-grad">Prove they work.</span>
            </h1>
            <p className="pk-lede">
              Design, trace, replay, and evaluate every agent decision in one reliability
              workspace—without stitching together five different tools.
            </p>
            <div className="pk-btns">
              <Link href={start} className="pk-btn pk-btn-primary">{startLabel} <Arrow /></Link>
              <Link href="/traces" className="pk-btn pk-btn-dark">Try the live sandbox <Play /></Link>
            </div>
            <div className="pk-hero-notes">
              <span><i />No credit card</span>
              <span><i />OpenTelemetry native</span>
              <span><i />Self-host ready</span>
            </div>
          </div>
          <FlowStudioMock />
        </div>
      </section>

      {/* ─────────────────────── Proof strip ────────────────────────── */}
      <section className="pk-proof pk-tone-paper">
        <div className="pk-shell pk-proof-in">
          <span className="pk-proof-label">Guided demo evidence</span>
          <div className="pk-proof-items">
            {PROOF.map((p) => (
              <div key={p.label} className="pk-proof-item"><b>{p.value}</b><span>{p.label}</span></div>
            ))}
          </div>
        </div>
      </section>

      {/* ─────────────────────── Stack rail ─────────────────────────── */}
      <section className="pk-rail pk-tone-paper">
        <div className="pk-rail-in">
          <div>
            <span className="pk-rail-h">Works with your stack</span>
            <strong className="pk-rail-title">Open standards in. Portable evidence out.</strong>
          </div>
          <div className="pk-rail-names">
            {STACK.map((n) => <span key={n}>{n}</span>)}
          </div>
        </div>
      </section>

      {/* ───────────────── One reliability workspace ────────────────── */}
      <section id="product" className="pk-section pk-tone-paper">
        <div className="pk-shell">
          <div className="pk-intro pk-reveal">
            <span className="pk-eyebrow">One reliability workspace</span>
            <h2 className="pk-h2">Everything between an idea<br />and a dependable agent.</h2>
            <p className="pk-lede">
              Build the flow, observe every decision, reproduce failures, and measure the fix
              without losing context between tools.
            </p>
          </div>
          <div className="pk-grid pk-grid-3">
            {CAPABILITIES.map((c) => (
              <article key={c.title} className="pk-card pk-reveal"
                style={{ "--ic": c.color, "--ic-bg": c.tint, "--glow": c.glow } as React.CSSProperties}>
                <span className="pk-card-ic"><Icon name={c.icon} /></span>
                <div className="pk-card-eyebrow">{c.eyebrow}</div>
                <h3>{c.title}</h3>
                <p>{c.body}</p>
                <Link href={c.href} className="pk-link">Explore <ArrowNE /></Link>
              </article>
            ))}
          </div>
        </div>
      </section>

      {/* ───────────────────────── Tour banner ──────────────────────── */}
      <section className="pk-tour pk-tone-paper">
        <div className="pk-shell">
          <div className="pk-tour-in pk-reveal">
            <div className="pk-tour-play"><Play /></div>
            <div className="pk-tour-copy">
              <span className="pk-eyebrow">4-minute interactive tour</span>
              <h2>Watch one agent go from failure to verified release.</h2>
              <p>
                Follow the complete ProveKit loop with realistic production data—flow design,
                nested trace, deterministic replay, and quality verdict included.
              </p>
            </div>
            <div className="pk-tour-stats">
              <div className="pk-tour-stat"><span>Trace depth</span><b>14 spans</b></div>
              <div className="pk-tour-stat"><span>Replay saving</span><b>−57% cost</b></div>
              <div className="pk-tour-stat"><span>Quality</span><b>94.2 score</b></div>
            </div>
            <Link href="/traces" className="pk-btn pk-btn-light">Open live sandbox <Arrow /></Link>
          </div>
        </div>
      </section>

      {/* ────────────────────── The reliability loop ────────────────── */}
      <section className="pk-section pk-tone-paper" style={{ paddingTop: 0 }}>
        <div className="pk-shell">
          <div className="pk-reveal" style={{ maxWidth: 780, marginBottom: 56 }}>
            <span className="pk-eyebrow">The reliability loop</span>
            <h2 className="pk-h2">From “it failed” to<br /><span className="pk-accent">exactly why.</span></h2>
            <p className="pk-lede">
              One continuous workflow turns every production run into evidence your team can
              inspect, reproduce, and improve.
            </p>
          </div>
          <div className="pk-grid pk-grid-3">
            {LOOP.map((s) => (
              <article key={s.title} className="pk-card pk-reveal"
                style={{ "--ic": "var(--violet)", "--ic-bg": "var(--violet-soft)" } as React.CSSProperties}>
                <span className="pk-card-ic"><Icon name={s.icon} /></span>
                <span className="pk-card-num">{s.num}</span>
                <div className="pk-card-eyebrow">{s.eyebrow}</div>
                <h3>{s.title}</h3>
                <p>{s.body}</p>
                <Link href={s.href} className="pk-link">Explore {s.eyebrow.toLowerCase()} <Arrow /></Link>
              </article>
            ))}
          </div>
        </div>
      </section>

      {/* ───────────────────────── Trace explorer ───────────────────── */}
      <section id="trace" className="pk-section pk-tone-dark">
        <div className="pk-shell pk-split">
          <div className="pk-reveal">
            <span className="pk-eyebrow">Trace explorer</span>
            <h2 className="pk-h2">See the<br />decision.<br />Not just the<br />output.</h2>
            <p className="pk-lede">
              Move from a fleet-wide signal to the exact span that changed. Prove where time,
              cost, and quality were lost with complete nested context.
            </p>
            <ul className="pk-checks">
              <li><span className="pk-tick">✓</span>Waterfall, flow graph, events, and metadata</li>
              <li><span className="pk-tick">✓</span>Input/output inspection with PII masking</li>
              <li><span className="pk-tick">✓</span>Session, model, token, latency, and cost attribution</li>
            </ul>
            <div className="pk-btns">
              <Link href="/traces" className="pk-btn pk-btn-dark">Inspect a production trace <Arrow /></Link>
            </div>
          </div>
          <div className="pk-split-visual pk-reveal"><TraceMock /></div>
        </div>
      </section>

      {/* ────────────────────── Replay + evaluate ───────────────────── */}
      <section id="replay" className="pk-section pk-tone-dark" style={{ paddingTop: 0 }}>
        <div className="pk-shell">
          <div className="pk-intro pk-reveal">
            <span className="pk-eyebrow">Replay + evaluate</span>
            <h2 className="pk-h2">Change the system.<br />Keep the evidence.</h2>
            <p className="pk-lede">
              Every rerun carries its configuration, provenance, structural diff, and quality verdict.
            </p>
          </div>
          <div className="pk-compare">
            <article className="pk-story pk-reveal">
              <div className="pk-story-top">
                <span className="pk-story-ic"><Icon name="replay" /></span>
                <span className="pk-story-tag">Deterministic</span>
              </div>
              <h3>Replay a failure faithfully.</h3>
              <p>Replace the prompt or model, preserve recorded tools, and see precisely where execution diverges.</p>
              <div className="pk-ab">
                <div>
                  <span>Original</span><b>1.84s</b>
                  <small>$0.0428 · 4,291 tokens</small>
                </div>
                <div className="pk-ab-arrow">→</div>
                <div>
                  <span>Candidate</span><b>1.12s</b>
                  <small>$0.0182 · 2,903 tokens</small>
                </div>
              </div>
              <div className="pk-verdict">
                <i><Icon name="shield" /></i>
                <div>
                  <b>Reliable comparison</b>
                  <small>No input-dependent tool spans changed.</small>
                </div>
              </div>
              <Link href="/replay" className="pk-link">Open replay workspace <ArrowNE /></Link>
            </article>

            <article className="pk-story pk-reveal">
              <div className="pk-story-top">
                <span className="pk-story-ic"><Icon name="spark" /></span>
                <span className="pk-story-tag">Quality passed</span>
              </div>
              <h3>Prove the candidate is better.</h3>
              <p>Compare correctness, groundedness, trajectory, latency, tokens, and cost against a versioned baseline.</p>
              <div className="pk-score-head">
                <div>
                  <span style={{ fontFamily: "var(--mono)", fontSize: 9.5, fontWeight: 600, letterSpacing: ".14em", textTransform: "uppercase", color: "#6d6780" }}>
                    Overall score
                  </span>
                  <div className="pk-score-big">94.2</div>
                  <div className="pk-score-delta">+4.8%</div>
                </div>
                <ScoreRing value={94} />
              </div>
              {SCORES.map((s) => (
                <div key={s.label} className="pk-score-row">
                  <span>{s.label}</span>
                  <span className="pk-score-track"><span className="pk-score-fill" style={{ width: `${s.value}%` }} /></span>
                  <b>{s.value}</b>
                </div>
              ))}
              <Link href="/experiments" className="pk-link">View experiment results <ArrowNE /></Link>
            </article>
          </div>
        </div>
      </section>

      {/* ──────────────────── Visual agent flow studio ──────────────── */}
      <section id="flow" className="pk-section pk-tone-paper">
        <div className="pk-shell pk-split pk-split-rev">
          <div className="pk-split-visual pk-reveal"><FlowCanvasMock /></div>
          <div className="pk-reveal">
            <span className="pk-eyebrow">Visual agent flow studio</span>
            <h2 className="pk-h2">Design, test, and debug on one living canvas.</h2>
            <p className="pk-lede">
              Build reusable workflows with AI agents, models, tools, logic, human approvals,
              triggers, and typed outputs—then execute them with trace evidence attached.
            </p>
            <div className="pk-chips">
              {["Drag-and-drop nodes", "Test execution", "Run history", "Version restore", "Input/output mapping", "Publish controls"].map((c) => (
                <span key={c}>{c}</span>
              ))}
            </div>
            <div className="pk-btns">
              <Link href="/flows" className="pk-btn pk-btn-primary">Open Agent Flow Studio <Arrow /></Link>
            </div>
          </div>
        </div>
      </section>

      {/* ───────────────────────── Ecosystem ────────────────────────── */}
      <section className="pk-section pk-tone-paper2">
        <div className="pk-shell">
          <div className="pk-intro pk-reveal">
            <span className="pk-eyebrow">Open by design</span>
            <h2 className="pk-h2">Meet your stack<br />where it already runs.</h2>
            <p className="pk-lede">
              Drop-in SDKs and OpenTelemetry-native ingestion keep your telemetry portable and
              your architecture flexible.
            </p>
          </div>
          <div className="pk-eco">
            <OrbitMock />
            <div className="pk-eco-side">
              <article className="pk-card pk-reveal">
                <span className="pk-card-ic"><Icon name="plug" /></span>
                <div className="pk-card-eyebrow">Ingest</div>
                <h3>OTLP JSON + protobuf</h3>
                <p>Preserve distributed trace context through collectors and custom instrumentation.</p>
                <a href={DOCS} target="_blank" rel="noreferrer" className="pk-link">OpenTelemetry guide <Arrow /></a>
              </article>
              <article className="pk-card pk-reveal">
                <span className="pk-card-ic"><Icon name="cloud" /></span>
                <div className="pk-card-eyebrow">Deploy</div>
                <h3>Cloud or self-hosted</h3>
                <p>Use the managed control plane or deploy with Helm inside your own infrastructure.</p>
                <a href={DOCS} target="_blank" rel="noreferrer" className="pk-link">Enterprise deployment <Arrow /></a>
              </article>
            </div>
          </div>
        </div>
      </section>

      {/* ─────────────────────── Enterprise control ─────────────────── */}
      <section id="trust" className="pk-section pk-tone-dark">
        <div className="pk-shell pk-split">
          <div className="pk-reveal">
            <span className="pk-story-tag" style={{ marginLeft: 0, display: "inline-flex", marginBottom: 26 }}>Enterprise control</span>
            <h2 className="pk-h2">Production<br />evidence,<br />governed your<br />way.</h2>
            <p className="pk-lede">
              Protect sensitive AI telemetry without sacrificing the detail your teams need to
              debug and improve it.
            </p>
            <div className="pk-btns">
              <a href="#assurance" className="pk-btn pk-btn-light">Open the trust center <Arrow /></a>
            </div>
          </div>
          <div className="pk-split-visual pk-grid pk-grid-2">
            {SECURITY.map((s) => (
              <article key={s.title} className="pk-card pk-card-dark pk-reveal" style={{ minHeight: 210 }}>
                <span className="pk-card-ic"><Icon name={s.icon} /></span>
                <h3 style={{ marginTop: 34, fontSize: 19 }}>{s.title}</h3>
                <p style={{ fontSize: 13.5 }}>{s.body}</p>
              </article>
            ))}
          </div>
        </div>
      </section>

      {/* ────────────────────── Trust architecture ──────────────────── */}
      <section id="assurance" className="pk-ledger pk-tone-paper">
        <div className="pk-shell pk-ledger-in pk-reveal">
          <div className="pk-ledger-intro">
            <span className="pk-ledger-ic"><Icon name="shield" /></span>
            <div>
              <span className="pk-eyebrow">Trust architecture</span>
              <h2>Enterprise control without a black box.</h2>
              <p>Keep the evidence your teams need while controlling identity, sensitive data, residency, retention, and deployment.</p>
            </div>
          </div>
          <div className="pk-ledger-items">
            {LEDGER.map((l) => (
              <div key={l.title} className="pk-ledger-item">
                <i><Icon name={l.icon} /></i>
                <div><b>{l.title}</b><small>{l.body}</small></div>
              </div>
            ))}
          </div>
          <div className="pk-ledger-actions">
            <Link href="/settings" className="pk-btn pk-btn-primary">Explore enterprise <Arrow /></Link>
            <Link href="/community" className="pk-link">Talk to an architect <ArrowNE /></Link>
          </div>
        </div>
      </section>

      {/* ─────────────────────── Open source SDK ────────────────────── */}
      <section className="pk-section pk-tone-dark">
        <div className="pk-shell pk-intro pk-reveal" style={{ marginBottom: 0 }}>
          <span className="pk-eyebrow">Open source SDK</span>
          <h2 className="pk-h2">Instrument once.<br />Understand everything.</h2>
          <p className="pk-lede">One decorator at the entrypoint. Full nested visibility from the first request.</p>
          <div className="pk-code">
            <pre>
              <span className="k">from</span> <span className="d">provekit</span> <span className="k">import</span> <span className="d">trace</span>{"\n\n"}
              <span className="d">@trace.agent(</span><span className="s">&quot;support-agent&quot;</span><span className="d">)</span>{"\n"}
              <span className="k">def</span> <span className="d">run(message: str):</span>{"\n"}
              {"    "}<span className="k">return</span> <span className="d">agent.invoke(message)</span>
            </pre>
          </div>
          <div className="pk-btns" style={{ justifyContent: "center" }}>
            <a href={DOCS} target="_blank" rel="noreferrer" className="pk-btn pk-btn-light">Read the quickstart <Arrow /></a>
          </div>
        </div>
      </section>

      {/* ────────────────────────── Teams ───────────────────────────── */}
      <section id="teams" className="pk-section pk-tone-paper">
        <div className="pk-shell">
          <div className="pk-intro pk-reveal">
            <span className="pk-eyebrow">One source of truth</span>
            <h2 className="pk-h2">Built for every team<br />responsible for AI.</h2>
          </div>
          <div className="pk-grid pk-grid-4">
            {TEAMS.map((t) => (
              <article key={t.title} className="pk-card pk-reveal" style={{ minHeight: 300 }}>
                <span className="pk-card-ic"><Icon name={t.icon} /></span>
                <h3 style={{ marginTop: 34 }}>{t.title}</h3>
                <p>{t.body}</p>
                <Link href={t.href} className="pk-link">See the workflow <ArrowNE /></Link>
              </article>
            ))}
          </div>
        </div>
      </section>

      {/* ───────────────────────── Pricing ──────────────────────────── */}
      <section id="pricing" className="pk-section pk-tone-paper2">
        <div className="pk-shell pk-pricing">
          <div className="pk-reveal">
            <span className="pk-eyebrow">Start without friction</span>
            <h2 className="pk-h2">Free to prove.<br />Ready to scale.</h2>
            <p className="pk-lede">
              Begin with 50,000 traces per month, core replay and evaluation, and no credit card.
              Move to team or enterprise controls when production demands it.
            </p>
            <div className="pk-btns">
              <Link href={start} className="pk-btn pk-btn-primary">Create free workspace <Arrow /></Link>
              <a href="#faq" className="pk-btn pk-btn-light">Compare plans</a>
            </div>
          </div>
          <div className="pk-plan pk-reveal">
            <div className="pk-plan-top">
              <span className="pk-plan-tag">Developer</span>
              <div className="pk-plan-price"><b>$0</b><span>/ month</span></div>
            </div>
            <ul>
              {["50k traces / month", "7-day retention", "Core replay & evaluation", "OpenTelemetry ingestion"].map((f) => (
                <li key={f}><i>✓</i>{f}</li>
              ))}
            </ul>
            <div className="pk-plan-foot">Team from $299 / month <ArrowNE /></div>
          </div>
        </div>
      </section>

      {/* ──────────────────────────── FAQ ──────────────────────────── */}
      <section id="faq" className="pk-section pk-tone-paper">
        <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify({
          "@context": "https://schema.org", "@type": "FAQPage",
          mainEntity: FAQ.map((f) => ({ "@type": "Question", name: f.q, acceptedAnswer: { "@type": "Answer", text: f.a } })),
        }) }} />
        <div className="pk-shell pk-faq">
          <div className="pk-reveal">
            <span className="pk-eyebrow">Common questions</span>
            <h2 className="pk-h2">Clear answers before<br />your first trace.</h2>
          </div>
          <div className="pk-faq-list pk-reveal">
            {FAQ.map((f, i) => (
              <div key={f.q} className="pk-faq-item">
                <button className="pk-faq-q" aria-expanded={faq === i} onClick={() => setFaq(faq === i ? -1 : i)}>
                  {f.q}<span>{faq === i ? "−" : "+"}</span>
                </button>
                {faq === i && <div className="pk-faq-a">{f.a}</div>}
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ─────────────────────── Final CTA ─────────────────────────── */}
      <section className="pk-final">
        <div className="pk-final-in pk-reveal">
          <span className="pk-tag-lime">Prove the next release</span>
          <h2 className="pk-display">Your agent already runs.<br />Now make it explainable.</h2>
          <p className="pk-lede" style={{ color: "#a9a3bb", marginInline: "auto" }}>
            Start tracing in minutes, or walk through the complete reliability loop with our team.
          </p>
          <div className="pk-btns">
            <Link href={start} className="pk-btn pk-btn-primary">{startLabel} <Arrow /></Link>
            <Link href="/community" className="pk-btn pk-btn-outline">Book a demo <ArrowNE /></Link>
          </div>
          <div className="pk-final-note">No credit card · OpenTelemetry native · Self-host ready</div>
        </div>
      </section>

      {/* ─────────────────────────  Footer  ────────────────────────── */}
      <footer className="pk-footer">
        <div className="pk-shell">
          <div className="pk-footer-top">
            <div className="pk-footer-brand">
              <span className="pk-wordmark"><Mark />PROVEKIT</span>
              <p>Evidence for every AI decision.</p>
              <span className="pk-status"><i className="pk-dot" />All core systems operational</span>
            </div>
            <div>
              <div className="pk-footer-legal">
                <Link href="/privacy">Privacy</Link>
                <Link href="/terms">Terms</Link>
                <a href={REPO} target="_blank" rel="noreferrer">Status</a>
              </div>
            </div>
          </div>
          <div className="pk-footer-cols">
            {FOOTER.map((col) => (
              <div key={col.h} className="pk-footer-col">
                <h4>{col.h}</h4>
                {col.links.map((l) => (
                  l.href.startsWith("/")
                    ? <Link key={l.t} href={l.href}>{l.t}</Link>
                    : <a key={l.t} href={l.href} target="_blank" rel="noreferrer">{l.t}</a>
                ))}
              </div>
            ))}
          </div>
          <div className="pk-footer-bottom">© 2026 ProveKit. Built for teams who verify.</div>
        </div>
      </footer>
    </div>
  );
}

/* ══════════════════════════ Product mockups ══════════════════════════ */

function FlowStudioMock() {
  return (
    <div className="pk-stage pk-reveal" aria-hidden>
      <div className="pk-stage-bar">
        <span className="pk-stage-mark">///</span>
        <span className="pk-crumb">Flows <span style={{ opacity: .45 }}>/</span> <b>Customer Support Agent</b></span>
        <span className="pk-live"><i />Live</span>
        <span className="pk-stage-actions">
          <span className="pk-chip-btn"><Play />Test</span>
          <span className="pk-chip-btn pk-solid">Publish</span>
        </span>
      </div>
      <div className="pk-stage-body">
        <div className="pk-palette">
          <div className="pk-palette-h">Building blocks</div>
          {BLOCKS.map((b) => (
            <div key={b.t} className="pk-block">
              <span className="pk-block-ic" style={{ background: b.bg }}><Icon name={b.icon} /></span>
              <span>
                <span className="pk-block-t">{b.t}</span>
                <span className="pk-block-s">{b.s}</span>
              </span>
              <span className="pk-block-add">+</span>
            </div>
          ))}
        </div>
        <div className="pk-canvas">
          <svg className="pk-wires" viewBox="0 0 100 100" preserveAspectRatio="none">
            <path d="M22,58 C30,58 32,30 46,30" vectorEffect="non-scaling-stroke" />
            <path d="M22,58 C32,58 34,80 46,80" vectorEffect="non-scaling-stroke" />
            <path d="M62,30 C74,30 74,58 84,58" vectorEffect="non-scaling-stroke" />
            <path d="M62,80 C74,80 74,58 84,58" vectorEffect="non-scaling-stroke" />
          </svg>
          <div className="pk-node" style={{ left: "2%", top: "48%" }}>
            <span className="pk-node-ic" style={{ background: "#2f9a63" }}><Icon name="bolt" /></span>
            <span><span className="pk-node-t">New request</span><span className="pk-node-s">Webhook trigger</span></span>
          </div>
          <div className="pk-node" style={{ left: "40%", top: "18%" }}>
            <span className="pk-node-ic" style={{ background: "var(--violet)" }}><Icon name="agent" /></span>
            <span><span className="pk-node-t">Knowledge agent</span><span className="pk-node-s">GPT-4.1 · 0.8s</span></span>
          </div>
          <div className="pk-node" style={{ left: "40%", top: "70%" }}>
            <span className="pk-node-ic" style={{ background: "#e0576f" }}><Icon name="branch" /></span>
            <span><span className="pk-node-t">Route intent</span><span className="pk-node-s">3 conditions</span></span>
          </div>
          <div className="pk-node pk-outline" style={{ left: "76%", top: "48%" }}>
            <span className="pk-node-ic" style={{ background: "var(--violet-dark)" }}><Icon name="shield" /></span>
            <span><span className="pk-node-t">Quality gate</span><span className="pk-node-s">Score ≥ 0.85</span></span>
          </div>
          <div className="pk-metric" style={{ right: 16, top: 14 }}>
            Latency <b>2.84s</b> <span className="pk-good">−18%</span>
          </div>
          <div className="pk-metric" style={{ left: 16, bottom: 14 }}>
            Quality <b>0.94</b> <span className="pk-good">passed</span>
          </div>
          <div className="pk-toast" style={{ right: 24, bottom: 14 }}>
            <span className="pk-toast-ic">✓</span>
            <span>
              <span className="pk-toast-t">Run completed</span>
              <span className="pk-toast-s">2.84s · $0.0382 · score 0.94</span>
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}

function TraceMock() {
  return (
    <div className="pk-trace" aria-hidden>
      <div className="pk-trace-top">
        <span className="pk-trace-id"><i />tr_a91f3c2</span>
        <span className="pk-badge-ok">● Success</span>
        <span className="pk-trace-dur">1.84s</span>
      </div>
      <div className="pk-trace-tabs">
        <button className="on">Waterfall</button><button>Flow graph</button>
        <button>Events</button><button>Metadata</button>
      </div>
      <div className="pk-wf">
        <div className="pk-wf-ruler"><span>0ms</span><span>500ms</span><span>1.0s</span><span>1.5s</span></div>
        {SPANS.map((s) => (
          <div key={s.name} className="pk-wf-row">
            <span className="pk-wf-name"><i style={{ background: s.color }} />{s.name}</span>
            <span className="pk-wf-track">
              <span className="pk-wf-bar" style={{ left: `${s.start}%`, width: `${s.width}%` }} />
            </span>
          </div>
        ))}
      </div>
      <div className="pk-trace-foot">
        <div><span>Selected span</span><b>llm · gpt-4.1</b></div>
        <div><span>Tokens</span><b>2,842</b></div>
        <div><span>Cost</span><b>$0.0284</b></div>
        <div><span>Quality</span><b className="pk-good">0.94</b></div>
      </div>
    </div>
  );
}

function FlowCanvasMock() {
  return (
    <div className="pk-flowcanvas" aria-hidden>
      <svg className="pk-wires" viewBox="0 0 100 100" preserveAspectRatio="none">
        <path d="M20,24 C34,24 32,58 44,58" vectorEffect="non-scaling-stroke" />
        <path d="M44,58 C34,58 40,24 54,24" vectorEffect="non-scaling-stroke" />
        <path d="M54,24 C70,24 62,80 74,80" vectorEffect="non-scaling-stroke" />
      </svg>
      <div className="pk-node" style={{ left: "4%", top: "16%" }}>
        <span className="pk-node-ic" style={{ background: "#2f9a63" }}><Icon name="bolt" /></span>
        <span><span className="pk-node-t">Webhook</span><span className="pk-node-s">trigger</span></span>
      </div>
      <div className="pk-node" style={{ left: "30%", top: "50%" }}>
        <span className="pk-node-ic" style={{ background: "#e0576f" }}><Icon name="branch" /></span>
        <span><span className="pk-node-t">Route intent</span><span className="pk-node-s">logic</span></span>
      </div>
      <div className="pk-node" style={{ left: "52%", top: "16%" }}>
        <span className="pk-node-ic" style={{ background: "var(--violet-dark)" }}><Icon name="shield" /></span>
        <span><span className="pk-node-t">Quality gate</span><span className="pk-node-s">score ≥ 0.85</span></span>
      </div>
      <div className="pk-node" style={{ left: "56%", top: "72%" }}>
        <span className="pk-node-ic" style={{ background: "var(--violet)" }}><Icon name="output" /></span>
        <span><span className="pk-node-t">Response</span><span className="pk-node-s">output</span></span>
      </div>
    </div>
  );
}

function OrbitMock() {
  // Eight integrations orbiting the ProveKit core — positioned on two rings.
  const nodes = [
    { t: "OpenAI", x: 50, y: 8 }, { t: "Anthropic", x: 79, y: 22 },
    { t: "LangChain", x: 88, y: 52 }, { t: "LlamaIndex", x: 76, y: 82 },
    { t: "CrewAI", x: 50, y: 93 }, { t: "AutoGen", x: 22, y: 82 },
    { t: "MCP", x: 12, y: 52 }, { t: "Webhooks", x: 22, y: 22 },
  ];
  return (
    <div className="pk-orbit pk-reveal" aria-hidden>
      <span className="pk-orbit-ring" style={{ width: "42%", aspectRatio: "1" }} />
      <span className="pk-orbit-ring" style={{ width: "68%", aspectRatio: "1" }} />
      <div className="pk-orbit-core">
        <div>
          <span className="pk-mark">///</span>
          <b>ProveKit</b>
          <small>OTLP evidence layer</small>
        </div>
      </div>
      {nodes.map((n) => (
        <span key={n.t} className="pk-orbit-node" style={{ left: `${n.x}%`, top: `${n.y}%`, transform: "translate(-50%, -50%)" }}>
          {n.t}
        </span>
      ))}
    </div>
  );
}

function ScoreRing({ value }: { value: number }) {
  const r = 38, c = 2 * Math.PI * r;
  return (
    <div className="pk-ring">
      <svg viewBox="0 0 88 88">
        <circle className="pk-ring-bg" cx="44" cy="44" r={r} />
        <circle className="pk-ring-fg" cx="44" cy="44" r={r} strokeDasharray={c} strokeDashoffset={c * (1 - value / 100)} />
      </svg>
      <b>{value}</b>
    </div>
  );
}

/* ══════════════════════════ Bits & icons ══════════════════════════ */

const Mark = () => <span className="pk-mark">///</span>;
const Arrow = () => <span className="pk-arrow" aria-hidden>→</span>;
const ArrowNE = () => <span className="pk-arrow" aria-hidden>↗</span>;
const Play = () => (
  <svg width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden>
    <path d="M5 3.5v9l8-4.5-8-4.5Z" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round" />
  </svg>
);

const PATHS: Record<string, string> = {
  agent: "M8 2a2 2 0 0 1 2 2v1h2a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2h2V4a2 2 0 0 1 2-2ZM6 9h.01M10 9h.01",
  model: "M8 2v3M8 11v3M2.5 8h3M10.5 8h3M4.2 4.2l2 2M9.8 9.8l2 2M11.8 4.2l-2 2M6.2 9.8l-2 2",
  search: "M7.2 12a4.8 4.8 0 1 0 0-9.6 4.8 4.8 0 0 0 0 9.6ZM11 11l3 3",
  branch: "M4.5 2v7a3 3 0 0 0 3 3h4M11.5 9.5 14 12l-2.5 2.5M4.5 2 2.5 4M4.5 2l2 2",
  shield: "M8 2 3 4v4c0 3 2.2 5.4 5 6 2.8-.6 5-3 5-6V4L8 2Zm-2 6 1.5 1.5L10.5 6.5",
  bolt: "M9 2 4 9h3l-1 5 5-7H8l1-5Z",
  trace: "M2 8h2.5l1.5-4 2 8 2-6 1.5 2H14",
  replay: "M13 8a5 5 0 1 1-1.6-3.7M13 2v3h-3",
  spark: "M8 2l1.6 3.9L13.5 7.5 9.6 9.1 8 13l-1.6-3.9L2.5 7.5l3.9-1.6L8 2Z",
  lock: "M4.5 7V5a3.5 3.5 0 1 1 7 0v2M3.5 7h9v6.5h-9V7Z",
  audit: "M4 2h6l3 3v9H4V2Zm2 5h5M6 10h5",
  data: "M2.5 4.5h11v3.5h-11V4.5Zm0 5h11V13h-11V9.5Z",
  plug: "M6 2v4M10 2v4M4.5 6h7v2.5a3.5 3.5 0 0 1-7 0V6ZM8 12v2.5",
  cloud: "M4.8 12.5a2.8 2.8 0 0 1-.3-5.6A4 4 0 0 1 12 7.4a2.6 2.6 0 0 1-.3 5.1H4.8Z",
  flask: "M6.5 2v4L3 12.5A1.2 1.2 0 0 0 4 14.5h8a1.2 1.2 0 0 0 1-2L9.5 6V2M5.5 2h5",
  gauge: "M2.5 11a5.5 5.5 0 1 1 11 0M8 11l3-3.2",
  building: "M4 14V3h8v11M6.5 6h.01M9.5 6h.01M6.5 9h.01M9.5 9h.01M7 14v-2.5h2V14",
  output: "M3 3.5h10v9H3v-9Zm2.5 3.5 2 2-2 2M9 11h2.5",
  approve: "M8 2 3 4v4c0 3 2.2 5.4 5 6 2.8-.6 5-3 5-6V4L8 2Z",
};

function Icon({ name }: { name: string }) {
  return (
    <svg width="1em" height="1em" viewBox="0 0 16 16" fill="none" aria-hidden
      style={{ display: "block", overflow: "visible" }}>
      <path d={PATHS[name] || PATHS.spark} stroke="currentColor" strokeWidth="1.35"
        strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

/** Fades sections in as they enter the viewport, matching the reference site. */
function useReveal() {
  const done = useRef(false);
  useEffect(() => {
    if (done.current) return;
    done.current = true;
    const els = Array.from(document.querySelectorAll<HTMLElement>(".pk-reveal"));
    if (!("IntersectionObserver" in window)) { els.forEach((e) => e.classList.add("pk-in")); return; }
    const io = new IntersectionObserver((entries) => {
      entries.forEach((e) => {
        if (e.isIntersecting) { e.target.classList.add("pk-in"); io.unobserve(e.target); }
      });
    }, { rootMargin: "0px 0px -12% 0px", threshold: 0.05 });
    els.forEach((e, i) => { e.style.transitionDelay = `${Math.min(i % 4, 3) * 70}ms`; io.observe(e); });
    return () => io.disconnect();
  }, []);
}

/* ══════════════════════════════ Content ══════════════════════════════ */

const PROOF = [
  { value: "14", label: "nested spans" },
  { value: "−57%", label: "replay cost" },
  { value: "+4.8%", label: "quality uplift" },
  { value: "94.2", label: "evaluation score" },
];

const STACK = ["OpenAI", "Anthropic", "LangChain", "LlamaIndex", "CrewAI", "AutoGen", "OpenTelemetry", "MCP"];

const BLOCKS = [
  { t: "AI Agent", s: "Reason & use tools", icon: "agent", bg: "var(--violet)" },
  { t: "LLM Model", s: "OpenAI, Anthropic", icon: "model", bg: "#3977df" },
  { t: "Knowledge", s: "Vector & web search", icon: "search", bg: "#d98324" },
  { t: "Logic", s: "Branch & transform", icon: "branch", bg: "#e0576f" },
  { t: "Approval", s: "Human in the loop", icon: "approve", bg: "#2f9a63" },
];

const CAPABILITIES = [
  { eyebrow: "Visual builder", title: "Agent Flow Studio", icon: "agent", href: "/flows",
    color: "var(--violet)", tint: "var(--violet-soft)", glow: "rgba(116,88,255,.16)",
    body: "Compose agents, models, tools, branches, approvals, and outputs on a production-ready canvas." },
  { eyebrow: "Observability", title: "Nested traces", icon: "trace", href: "/traces",
    color: "#3977df", tint: "#e6eeff", glow: "rgba(77,143,255,.16)",
    body: "Inspect model calls, tools, retrievals, sub-agents, tokens, latency, and cost in one evidence graph." },
  { eyebrow: "Debugging", title: "Deterministic replay", icon: "replay", href: "/replay",
    color: "#e0576f", tint: "#ffeaee", glow: "rgba(255,117,102,.16)",
    body: "Change inputs or prompts while reusing recorded tool responses for a reliable structural comparison." },
  { eyebrow: "Quality", title: "Evaluations", icon: "spark", href: "/experiments",
    color: "#2c9d7d", tint: "#e2f5ee", glow: "rgba(44,157,125,.16)",
    body: "Score datasets and production runs with LLM judges, RAG, trajectory, cost, and custom evaluators." },
  { eyebrow: "Control", title: "Prompt registry", icon: "audit", href: "/prompts",
    color: "#7658ee", tint: "#ece8ff", glow: "rgba(118,88,238,.16)",
    body: "Version, test, publish, compare, and roll back prompts with experiment provenance attached." },
  { eyebrow: "Regression", title: "Datasets & experiments", icon: "flask", href: "/datasets",
    color: "#be7925", tint: "#fff2e0", glow: "rgba(255,186,81,.18)",
    body: "Turn production failures into versioned test cases and compare every release against a trusted baseline." },
];

const LOOP = [
  { num: "01", eyebrow: "Trace", title: "Capture the whole story", icon: "trace", href: "/traces",
    body: "Every model call, tool execution, and sub-agent step—mapped into one complete, searchable trace." },
  { num: "02", eyebrow: "Replay", title: "Reproduce, don’t guess", icon: "replay", href: "/replay",
    body: "Edit prompts, replay recorded responses, and see structural diffs without inventing tool outputs." },
  { num: "03", eyebrow: "Evaluate", title: "Prove the improvement", icon: "shield", href: "/experiments",
    body: "Run deterministic datasets and online scorers. Compare quality, latency, tokens, and cost." },
];

const SPANS = [
  { name: "agent.run", start: 0, width: 100, color: "var(--violet)" },
  { name: "intent.classify", start: 6, width: 18, color: "#6d6780" },
  { name: "llm · gpt-4.1", start: 12, width: 40, color: "#3977df" },
  { name: "tool · search_docs", start: 18, width: 32, color: "#d98324" },
  { name: "vector.query", start: 24, width: 12, color: "#d98324" },
  { name: "llm · gpt-4.1", start: 26, width: 36, color: "#3977df" },
  { name: "response.validate", start: 26, width: 16, color: "#6d6780" },
];

const SCORES = [
  { label: "Correctness", value: 96 },
  { label: "Groundedness", value: 98 },
  { label: "Trajectory", value: 91 },
  { label: "Cost efficiency", value: 88 },
];

const SECURITY = [
  { title: "SSO + SCIM", icon: "lock", body: "OIDC, PKCE, automated deprovisioning" },
  { title: "PII protection", icon: "shield", body: "Mask sensitive values before storage" },
  { title: "Immutable audit", icon: "audit", body: "Evidence for every privileged action" },
  { title: "Data control", icon: "data", body: "Regional retention and self-hosting" },
];

const LEDGER = [
  { title: "SSO + SCIM", icon: "lock", body: "Lifecycle-controlled access" },
  { title: "PII masking", icon: "shield", body: "Protect payloads before storage" },
  { title: "Audit evidence", icon: "audit", body: "Trace every privileged action" },
  { title: "Self-hosted Helm", icon: "data", body: "Your cloud, region, or cluster" },
];

const TEAMS = [
  { title: "AI engineering", icon: "model", href: "/traces",
    body: "Debug agent behavior across models, tools, retrieval, and orchestration." },
  { title: "Evaluation teams", icon: "flask", href: "/experiments",
    body: "Turn edge cases into datasets and every release into a measured experiment." },
  { title: "AI operations", icon: "gauge", href: "/dashboard",
    body: "Monitor reliability, cost, quality, alerts, fleet health, and retention." },
  { title: "Enterprise leaders", icon: "building", href: "/settings",
    body: "Govern identity, sensitive data, access, residency, and deployment." },
];

const FAQ = [
  { q: "Do I need to replace my existing observability stack?",
    a: "No. ProveKit accepts OpenTelemetry data and complements your existing logs and infrastructure monitoring with agent-specific replay and evaluation." },
  { q: "Can replay call live tools?",
    a: "Yes. Use recorded-response mode for deterministic comparison or explicitly choose live tool re-execution when validating real integrations." },
  { q: "Which models and frameworks are supported?",
    a: "ProveKit works with OpenAI, Anthropic, LangChain, LlamaIndex, CrewAI, AutoGen, custom agents, OpenTelemetry collectors, webhooks, and MCP." },
  { q: "Can we keep trace data inside our infrastructure?",
    a: "Yes. Enterprise teams can use self-hosted Helm deployment, regional retention, PII masking, SSO, SCIM, RBAC, and audited support access." },
];

const FOOTER = [
  { h: "Product", links: [
    { t: "Live sandbox", href: "/traces" }, { t: "Tracing", href: "/traces" },
    { t: "Replay", href: "/replay" }, { t: "Evaluations", href: "/experiments" },
    { t: "Prompts", href: "/prompts" }, { t: "Monitoring", href: "/dashboard" },
  ] },
  { h: "Developers", links: [
    { t: "Documentation", href: DOCS }, { t: "Integrations", href: `${DOCS}/integrations.md` },
    { t: "OpenTelemetry", href: `${DOCS}/opentelemetry.md` }, { t: "SDKs & APIs", href: `${REPO}/tree/main/clients` },
    { t: "Changelog", href: `${REPO}/blob/main/CHANGELOG.md` },
  ] },
  { h: "Company", links: [
    { t: "Enterprise", href: "/settings" }, { t: "Trust center", href: "/#trust" },
    { t: "Security", href: `${REPO}/blob/main/SECURITY.md` }, { t: "Pricing", href: "/#pricing" },
    { t: "About", href: "/blog" }, { t: "Contact", href: "/community" },
  ] },
];
