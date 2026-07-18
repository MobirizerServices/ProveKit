"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { api } from "@/lib/api";

function VerifyInner() {
  const router = useRouter();
  const token = useSearchParams().get("token") || "";
  const [state, setState] = useState<"working" | "ok" | "bad">("working");

  useEffect(() => {
    if (!token) { setState("bad"); return; }
    api.verifyEmail(token)
      .then(() => { setState("ok"); setTimeout(() => router.push("/console"), 1500); })
      .catch(() => setState("bad"));
  }, [token, router]);

  return (
    <div className="auth-wrap">
      <div className="auth-card">
        <div className="auth-brand"><span className="logo">◇</span>Agent<b>Man</b></div>
        {state === "working" && <div className="auth-sub">Verifying your email…</div>}
        {state === "ok" && <div className="auth-note">Email verified ✓ Signing you in…</div>}
        {state === "bad" && <>
          <div className="auth-err">This verification link is invalid or has expired.</div>
          <div className="auth-switch"><a href="/login">← Back to sign in</a></div>
        </>}
      </div>
    </div>
  );
}

export default function VerifyPage() {
  return <Suspense fallback={null}><VerifyInner /></Suspense>;
}
