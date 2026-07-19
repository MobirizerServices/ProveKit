import { ImageResponse } from "next/og";

export const size = { width: 32, height: 32 };
export const contentType = "image/png";

// The ◇ brand mark on charcoal — used as the favicon/tab icon.
export default function Icon() {
  return new ImageResponse(
    (
      <div style={{ width: "100%", height: "100%", display: "flex", alignItems: "center",
        justifyContent: "center", background: "#0c0c0e" }}>
        <div style={{ width: 15, height: 15, background: "#d8b45f", transform: "rotate(45deg)", borderRadius: 2 }} />
      </div>
    ),
    { ...size }
  );
}
