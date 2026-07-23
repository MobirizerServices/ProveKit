"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";

// Only allow same-origin relative paths, so ?next=https://evil.example can't turn the auth
// page into an open redirect for phishing. Requires a single leading slash NOT followed by
// "/" or "\" — both of which browsers can treat as protocol-relative.
function safeNext(raw: string | null): string {
  const n = raw || "/dashboard";
  return /^\/(?![/\\])/.test(n) ? n : "/dashboard";
}

/**
 * Split-panel auth: a dark "evidence" panel that carries the product's line, and a light form
 * panel. SSO ("Continue with …") appears only when the backend reports it enabled, so there's
 * never a dead button.
 */
export default function AuthForm({ initial }: { initial: "login" | "signup" }) {
  const router = useRouter();
  const params = useSearchParams();
  const next = safeNext(params.get("next"));
  const [mode, setMode] = useState<"login" | "signup">(initial);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [sso, setSso] = useState<{ enabled: boolean; label: string; start_url: string } | null>(null);

  useEffect(() => { api.ssoConfig().then((c) => setSso(c)).catch(() => {}); }, []);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true); setErr("");
    try {
      if (mode === "login") await api.login(email, password);
      else await api.register(email, password, name);
      router.push(next);
    } catch (e: any) {
      const m = String(e?.message || e);
      setErr(m.includes("401") ? "Invalid email or password."
        : m.includes("409") ? "That email is already registered."
        : m.includes("400") ? "Password must be at least 8 characters." : m);
    } finally { setBusy(false); }
  };

  const signup = mode === "signup";
  return (
    <div className="split">
      {/* ── evidence panel ── */}
      <aside className="split-aside">
        <div className="split-aside-top">
          <Link href="/" className="split-brand"><span className="split-mark">///</span>PROVEKIT</Link>
        </div>
        <div className="split-aside-body">
          <span className="split-badge">Production ready</span>
          <h2>Every agent run<br />becomes evidence.</h2>
          <p>Trace. Replay. Evaluate. Improve.</p>
        </div>
        <div className="split-aside-foot">© 2026 ProveKit</div>
      </aside>

      {/* ── form panel ── */}
      <main className="split-main">
        <form className="split-form" onSubmit={submit}>
          <h1>{signup ? "Create your workspace" : "Welcome back"}</h1>
          <p className="split-sub">{signup ? "Start proving your agents work." : "Sign in to your ProveKit workspace."}</p>

          {sso?.enabled && (
            <>
              <a className="split-sso" href={sso.start_url}>
                <span className="split-sso-ic">◎</span>{sso.label || "Continue with SSO"}
              </a>
              <div className="split-or"><span>or continue with email</span></div>
            </>
          )}

          {signup && (
            <label className="split-field">
              <span>Name <em>optional</em></span>
              <input value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" />
            </label>
          )}
          <label className="split-field">
            <span>Work email</span>
            <input type="email" required value={email} onChange={(e) => setEmail(e.target.value)}
              autoComplete="email" autoFocus placeholder="you@company.com" />
          </label>
          <label className="split-field">
            <span>Password</span>
            <input type="password" required value={password} onChange={(e) => setPassword(e.target.value)}
              autoComplete={signup ? "new-password" : "current-password"}
              placeholder={signup ? "at least 8 characters" : ""} />
          </label>

          {err && <div className="split-err">{err}</div>}

          <button className="split-submit" type="submit" disabled={busy}>
            {busy ? "…" : signup ? "Create account" : "Sign in"} <span aria-hidden>→</span>
          </button>

          <div className="split-switch">
            {signup
              ? <>Have an account? <Link href="/login">Sign in</Link></>
              : <>Don&apos;t have an account? <Link href="/signup">Create one free</Link> · <Link href="/forgot">Forgot password?</Link></>}
          </div>
        </form>
      </main>
    </div>
  );
}
