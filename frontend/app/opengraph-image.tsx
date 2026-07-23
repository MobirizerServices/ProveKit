import { ImageResponse } from "next/og";

export const runtime = "edge";
export const alt = "ProveKit — Build agents. Prove they work.";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

// Generated share card — no image asset needed. Violet-on-ink to match the brand,
// with the trace → replay → evaluate loop that carries the whole value prop.
export default function OpengraphImage() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          background: "linear-gradient(135deg, #0d0c12 48%, #2a1c5c)",
          padding: "72px 80px",
          fontFamily: "sans-serif",
          color: "#f2f1f6",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", fontSize: 34, fontWeight: 700 }}>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              width: 46,
              height: 46,
              background: "linear-gradient(150deg, #8f79ff, #5b3ff0)",
              borderRadius: 13,
              marginRight: 20,
              fontSize: 22,
              fontWeight: 900,
              letterSpacing: "-0.08em",
              color: "#fff",
            }}
          >
            ///
          </div>
          <span>ProveKit</span>
        </div>

        <div style={{ display: "flex", flexDirection: "column" }}>
          <div style={{ fontSize: 76, fontWeight: 800, letterSpacing: "-0.03em", lineHeight: 1.03 }}>
            Build agents. Prove they work.
          </div>
          <div style={{ display: "flex", fontSize: 30, color: "#bdb7cc", marginTop: 24 }}>
            Trace → replay → evaluate every agent decision, in one workspace.
          </div>
        </div>

        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
          }}
        >
          <div
            style={{
              display: "flex",
              alignItems: "center",
              fontSize: 28,
              fontFamily: "monospace",
              color: "#9b96ab",
              background: "#16151f",
              border: "1px solid #2f2c40",
              borderRadius: 12,
              padding: "16px 24px",
            }}
          >
            <span style={{ color: "#9a82ff" }}>@trace.agent</span>
            <span style={{ margin: "0 12px" }}>→</span>
            <span style={{ color: "#b3a1ff" }}>nested flow</span>
            <span style={{ margin: "0 12px" }}>→</span>
            <div
              style={{
                width: 14,
                height: 14,
                borderRadius: 7,
                background: "#55c98a",
                marginRight: 10,
              }}
            />
            <span style={{ color: "#55c98a", fontWeight: 700 }}>passed</span>
          </div>
          <div style={{ display: "flex", fontSize: 24, color: "#6f6a80" }}>OpenTelemetry native · self-host ready</div>
        </div>
      </div>
    ),
    { ...size },
  );
}
