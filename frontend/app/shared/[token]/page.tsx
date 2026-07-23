"use client";

import { use, useEffect, useState } from "react";
import { api, TraceSpan } from "@/lib/api";
import TraceDetail from "@/components/TraceDetail";

// Public, read-only view of a shared trace. No login: the signed token in the URL is the
// only credential, verified server-side by GET /v1/share/{token}.
export default function SharedTracePage({ params }: { params: Promise<{ token: string }> }) {
  const { token } = use(params);
  const [spans, setSpans] = useState<TraceSpan[] | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    api.sharedTrace(token).then(setSpans).catch(() => setError(true));
  }, [token]);

  return (
    <main style={{ maxWidth: 1000, margin: "0 auto", padding: "24px 20px 80px" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 16 }}>
        <span className="brand"><span className="logo">///</span>ProveKit</span>
        <span className="muted" style={{ fontSize: 12.5 }}>shared trace · read-only</span>
      </div>
      <div style={{ background: "var(--panel)", border: "1px solid var(--border)", borderRadius: 12, padding: 16, minHeight: 200 }}>
        {error ? (
          <div className="muted" style={{ fontSize: 13 }}>This share link is invalid or has expired.</div>
        ) : !spans ? (
          <div className="muted" style={{ fontSize: 13 }}>Loading…</div>
        ) : (
          <TraceDetail spans={spans} readOnly />
        )}
      </div>
    </main>
  );
}
