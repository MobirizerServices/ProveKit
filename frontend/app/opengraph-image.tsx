import { ImageResponse } from "next/og";

export const runtime = "edge";
export const alt = "ProveKit — Prove any AI agent works";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

// Generated share card — no image asset needed. Gold-on-charcoal to match the brand,
// with the ✓ passed motif that carries the whole value prop.
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
          background: "linear-gradient(135deg, #0c0c0e 55%, #1a1408)",
          padding: "72px 80px",
          fontFamily: "sans-serif",
          color: "#eeeef2",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", fontSize: 34, fontWeight: 700 }}>
          <div
            style={{
              width: 22,
              height: 22,
              background: "#d8b45f",
              transform: "rotate(45deg)",
              marginRight: 20,
            }}
          />
          <span>ProveKit</span>
        </div>

        <div style={{ display: "flex", flexDirection: "column" }}>
          <div style={{ fontSize: 80, fontWeight: 800, letterSpacing: "-0.03em", lineHeight: 1.02 }}>
            Prove any AI agent works.
          </div>
          <div style={{ display: "flex", fontSize: 30, color: "#c9c9d2", marginTop: 24 }}>
            Test any agent — LLM · MCP · HTTP · A2A. No SDK.
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
              color: "#97979f",
              background: "#16161a",
              border: "1px solid #2e2e39",
              borderRadius: 12,
              padding: "16px 24px",
            }}
          >
            <span style={{ color: "#d8b45f" }}>run</span>
            <span style={{ margin: "0 12px" }}>→</span>
            <span style={{ color: "#e6c877" }}>+assert</span>
            <span style={{ margin: "0 12px" }}>→</span>
            <div
              style={{
                width: 14,
                height: 14,
                borderRadius: 7,
                background: "#3ddc84",
                marginRight: 10,
              }}
            />
            <span style={{ color: "#3ddc84", fontWeight: 700 }}>passed</span>
          </div>
          <div style={{ display: "flex", fontSize: 24, color: "#6b6b76" }}>open source · MIT</div>
        </div>
      </div>
    ),
    { ...size },
  );
}
