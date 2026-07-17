"use client";

// Catches errors in the root layout itself (must render its own <html>/<body>).
export default function GlobalError({ error, reset }: { error: Error; reset: () => void }) {
  return (
    <html lang="en">
      <body style={{ margin: 0, background: "#0c0d12", color: "#e7e9f0", fontFamily: "system-ui, sans-serif" }}>
        <div style={{ minHeight: "100vh", display: "grid", placeItems: "center", padding: 24 }}>
          <div style={{ textAlign: "center", maxWidth: 420 }}>
            <div style={{ fontSize: 40 }}>⚠</div>
            <h2>AgentMan hit an unexpected error</h2>
            <p style={{ color: "#8b91a4" }}>{error?.message || "Please reload."}</p>
            <button onClick={reset} style={{ marginTop: 12, padding: "8px 16px", borderRadius: 8, border: "none", background: "#7c6cff", color: "#fff", cursor: "pointer" }}>Reload</button>
          </div>
        </div>
      </body>
    </html>
  );
}
