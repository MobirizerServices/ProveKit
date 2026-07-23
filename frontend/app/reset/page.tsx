"use client";

import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { api } from "@/lib/api";

function ResetForm() {
  const router = useRouter();
  const token = useSearchParams().get("token") || "";
  const [password, setPassword] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true); setErr("");
    try {
      await api.resetPassword(token, password);
      setDone(true);
      setTimeout(() => router.push("/login"), 1500);
    } catch (e: any) {
      const m = String(e?.message || e);
      setErr(m.includes("400") ? "This reset link is invalid or has expired." : m);
    } finally { setBusy(false); }
  };

  return (
    <div className="auth-wrap">
      <form className="auth-card" onSubmit={submit}>
        <div className="auth-brand"><span className="logo">///</span>ProveKit</div>
        <div className="auth-sub">Choose a new password</div>
        {!token && <div className="auth-err">Missing reset token — use the link from your email.</div>}
        {done ? (
          <div className="auth-note">Password updated. Redirecting to sign in…</div>
        ) : (
          <>
            <div className="field"><label>New password</label><input type="password" required value={password} onChange={(e) => setPassword(e.target.value)} placeholder="at least 8 characters" autoComplete="new-password" autoFocus /></div>
            {err && <div className="auth-err">{err}</div>}
            <button className="btn btn-run" type="submit" disabled={busy || !token} style={{ width: "100%", marginTop: 4 }}>{busy ? "…" : "Reset password"}</button>
          </>
        )}
        <div className="auth-switch"><a href="/login">← Back to sign in</a></div>
      </form>
    </div>
  );
}

export default function ResetPage() {
  return <Suspense fallback={null}><ResetForm /></Suspense>;
}
