import { ImageResponse } from "next/og";

export const size = { width: 32, height: 32 };
export const contentType = "image/png";

// The /// brand mark on a violet tile — used as the favicon/tab icon.
export default function Icon() {
  return new ImageResponse(
    (
      <div style={{ width: "100%", height: "100%", display: "flex", alignItems: "center",
        justifyContent: "center", background: "linear-gradient(150deg, #8f79ff, #5b3ff0)", borderRadius: 8 }}>
        <div style={{ display: "flex", fontSize: 19, fontWeight: 900, color: "#fff", letterSpacing: "-0.08em" }}>///</div>
      </div>
    ),
    { ...size }
  );
}
