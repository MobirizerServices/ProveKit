"use client";

import { useState } from "react";
import { api } from "@/lib/api";

export default function ForgotPage() {
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try { await api.forgotPassword(email); } catch {}
    setSent(true); setBusy(false);
  };

  return (
    <div className="auth-wrap">
      <form className="auth-card" onSubmit={submit}>
        <div className="auth-brand"><span className="logo">///</span>ProveKit</div>
        <div className="auth-sub">Reset your password</div>
        {sent ? (
          <div className="auth-note">If an account exists for <b>{email}</b>, a reset link is on its way. Check your inbox (and, if self-hosting without SMTP, your server logs).</div>
        ) : (
          <>
            <div className="field"><label>Email</label><input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} autoFocus autoComplete="email" /></div>
            <button className="btn btn-run" type="submit" disabled={busy} style={{ width: "100%", marginTop: 4 }}>{busy ? "…" : "Send reset link"}</button>
          </>
        )}
        <div className="auth-switch"><a href="/login">← Back to sign in</a></div>
      </form>
    </div>
  );
}
