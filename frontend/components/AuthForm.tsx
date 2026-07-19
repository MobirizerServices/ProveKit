"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { api } from "@/lib/api";

// Only allow same-origin relative paths, so ?next=https://evil.example can't turn the auth
// page into an open redirect for phishing. Requires a single leading slash NOT followed by
// "/" or "\" — both of which browsers can treat as protocol-relative.
function safeNext(raw: string | null): string {
  const n = raw || "/traces";
  return /^\/(?![/\\])/.test(n) ? n : "/traces";
}

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

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true); setErr("");
    try {
      if (mode === "login") await api.login(email, password);
      else await api.register(email, password, name);
      router.push(next);
    } catch (e: any) {
      const m = String(e?.message || e);
      setErr(m.includes("401") ? "Invalid email or password." : m.includes("409") ? "That email is already registered." : m.includes("400") ? "Password must be at least 8 characters." : m);
    } finally { setBusy(false); }
  };

  const signup = mode === "signup";
  return (
    <div className="auth-wrap">
      <form className="auth-card" onSubmit={submit}>
        <Link href="/" className="auth-brand" style={{ textDecoration: "none", color: "inherit" }}>
          <span className="logo">◇</span>Prove<b>Kit</b>
        </Link>
        <div className="auth-sub">{signup ? "Create your account" : "Sign in to your workspace"}</div>
        {signup && (
          <div className="field"><label>Name</label><input value={name} onChange={(e) => setName(e.target.value)} placeholder="optional" autoComplete="name" /></div>
        )}
        <div className="field"><label>Email</label><input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" autoFocus /></div>
        <div className="field"><label>Password</label><input type="password" required value={password} onChange={(e) => setPassword(e.target.value)} autoComplete={signup ? "new-password" : "current-password"} placeholder={signup ? "at least 8 characters" : ""} /></div>
        {err && <div className="auth-err">{err}</div>}
        <button className="btn btn-run" type="submit" disabled={busy} style={{ width: "100%", marginTop: 4 }}>{busy ? "…" : signup ? "Create account" : "Sign in"}</button>
        <div className="auth-switch">
          {signup
            ? <>Have an account? <Link href="/login">Sign in</Link></>
            : <>No account? <Link href="/signup">Sign up</Link> · <Link href="/forgot">Forgot password?</Link></>}
        </div>
      </form>
    </div>
  );
}
