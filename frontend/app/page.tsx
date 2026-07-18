"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";

export default function Landing() {
  const [authed, setAuthed] = useState(false);
  useEffect(() => { api.me().then(() => setAuthed(true)).catch(() => {}); }, []);
  const cta = authed ? "/traces" : "/login";

  return (
    <main style={wrap}>
      <div style={{ maxWidth: 780, textAlign: "center" }}>
        <div style={{ fontSize: 34, fontWeight: 700, letterSpacing: -0.5 }}>
          <span style={{ color: "var(--accent)" }}>◇</span> ProveKit
        </div>
        <h1 style={{ fontSize: 40, lineHeight: 1.12, margin: "18px 0 0", letterSpacing: -1 }}>
          Drop-in tracing for any AI agent.
        </h1>
        <p style={{ fontSize: 17, color: "var(--muted)", maxWidth: 560, margin: "16px auto 0", lineHeight: 1.5 }}>
          Add one decorator, get a project key, and review every run your agent makes —
          the model calls, the tools, the whole flow. No connections to configure, no
          framework lock-in. Open source and self-hostable.
        </p>

        <div style={{ display: "flex", gap: 12, justifyContent: "center", margin: "28px 0 40px" }}>
          <Link href={cta} className="btn" style={{ padding: "11px 22px", fontSize: 15 }}>Get started</Link>
          <a href="https://github.com/MobirizerServices/ProveKit" className="btn btn-ghost" style={{ padding: "11px 22px", fontSize: 15 }}>GitHub</a>
        </div>

        <pre style={code}>{`pip install "provekit[trace]"

# .env  (key from your project in the portal)
PROVEKIT_API_KEY=pk_...
PROVEKIT_ENDPOINT=https://your-provekit-host

import provekit.trace as pk

@pk.trace(name="my-agent")
def run_agent(question: str) -> str:
    ...   # every run shows up in your portal`}</pre>

        <div style={{ display: "flex", gap: 24, justifyContent: "center", marginTop: 36, flexWrap: "wrap" }}>
          {STEPS.map((st) => (
            <div key={st.n} style={{ width: 210, textAlign: "left" }}>
              <div style={{ color: "var(--accent)", fontWeight: 700, fontSize: 13 }}>{st.n}</div>
              <div style={{ fontWeight: 600, fontSize: 14, margin: "4px 0 3px" }}>{st.t}</div>
              <div className="muted" style={{ fontSize: 13, lineHeight: 1.45 }}>{st.d}</div>
            </div>
          ))}
        </div>
      </div>
    </main>
  );
}

const STEPS = [
  { n: "1", t: "Create a project", d: "Sign in and grab a project key — one per app or environment." },
  { n: "2", t: "Add the decorator", d: "pip install, drop the key in .env, wrap your agent's entrypoint." },
  { n: "3", t: "Review the flow", d: "Every run streams to the portal — inspect each step's input and output." },
];

const wrap: React.CSSProperties = {
  minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center", padding: "40px 20px",
};
const code: React.CSSProperties = {
  textAlign: "left", margin: "0 auto", maxWidth: 560, padding: 18, borderRadius: 12,
  background: "var(--panel)", border: "1px solid var(--border-strong)", fontSize: 12.5,
  lineHeight: 1.6, fontFamily: "var(--font-mono)", overflowX: "auto", whiteSpace: "pre",
};
