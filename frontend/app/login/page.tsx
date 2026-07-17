"use client";

import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { api } from "@/lib/api";

function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const next = params.get("next") || "/";
  const [mode, setMode] = useState<"login" | "signup">("login");
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

  return (
    <div className="auth-wrap">
      <form className="auth-card" onSubmit={submit}>
        <div className="auth-brand"><span className="logo">◇</span>Agent<b>Man</b></div>
        <div className="auth-sub">{mode === "login" ? "Sign in to your workspace" : "Create your account"}</div>
        {mode === "signup" && (
          <div className="field"><label>Name</label><input value={name} onChange={(e) => setName(e.target.value)} placeholder="optional" autoComplete="name" /></div>
        )}
        <div className="field"><label>Email</label><input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" autoFocus /></div>
        <div className="field"><label>Password</label><input type="password" required value={password} onChange={(e) => setPassword(e.target.value)} autoComplete={mode === "login" ? "current-password" : "new-password"} placeholder={mode === "signup" ? "at least 8 characters" : ""} /></div>
        {err && <div className="auth-err">{err}</div>}
        <button className="btn btn-run" type="submit" disabled={busy} style={{ width: "100%", marginTop: 4 }}>{busy ? "…" : mode === "login" ? "Sign in" : "Create account"}</button>
        <div className="auth-switch">
          {mode === "login" ? <>No account? <a onClick={() => { setMode("signup"); setErr(""); }}>Sign up</a></> : <>Have an account? <a onClick={() => { setMode("login"); setErr(""); }}>Sign in</a></>}
          {mode === "login" && <> · <a href="/forgot">Forgot password?</a></>}
        </div>
      </form>
    </div>
  );
}

export default function LoginPage() {
  return <Suspense fallback={null}><LoginForm /></Suspense>;
}
