"use client";

// Catches errors in the root layout itself (must render its own <html>/<body>).
export default function GlobalError({ error, reset }: { error: Error; reset: () => void }) {
  return (
    <html lang="en">
      {/* Colours are inlined, not tokens: this replaces the root layout, so globals.css
          never loads here. Keep these in step with :root in app/globals.css. */}
      <body style={{ margin: 0, background: "#0b0a10", color: "#f2f1f6", fontFamily: "system-ui, sans-serif" }}>
        <div style={{ minHeight: "100vh", display: "grid", placeItems: "center", padding: 24 }}>
          <div style={{ textAlign: "center", maxWidth: 420 }}>
            <div style={{ fontSize: 40 }}>⚠</div>
            <h2 style={{ letterSpacing: "-0.028em" }}>ProveKit hit an unexpected error</h2>
            <p style={{ color: "#9b96ab" }}>{error?.message || "Please reload."}</p>
            <button onClick={reset} style={{ marginTop: 12, padding: "9px 19px", borderRadius: 10, border: "none", background: "#7458ff", color: "#fff", fontWeight: 600, cursor: "pointer" }}>Reload</button>
          </div>
        </div>
      </body>
    </html>
  );
}
