import { ImageResponse } from "next/og";
import { getPost, POSTS } from "@/lib/posts";

export const alt = "ProveKit blog post";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export function generateStaticParams() {
  return POSTS.map((p) => ({ slug: p.slug }));
}

// Per-post share card so each blog link gets its own title on social.
export default async function OG({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const post = getPost(slug);
  const title = post?.title || "ProveKit Blog";
  return new ImageResponse(
    (
      <div style={{ width: "100%", height: "100%", display: "flex", flexDirection: "column",
        justifyContent: "space-between", background: "linear-gradient(135deg, #0c0c0e 55%, #1a1408)",
        padding: "72px 80px", fontFamily: "sans-serif", color: "#eeeef2" }}>
        <div style={{ display: "flex", alignItems: "center", fontSize: 30, fontWeight: 700 }}>
          <div style={{ width: 20, height: 20, background: "#d8b45f", transform: "rotate(45deg)", marginRight: 18 }} />
          <span>ProveKit Blog</span>
        </div>
        <div style={{ fontSize: 60, fontWeight: 800, letterSpacing: "-0.02em", lineHeight: 1.08 }}>{title}</div>
        <div style={{ fontSize: 26, color: "#c9c9d2" }}>Drop-in tracing · evaluation · observability for AI agents</div>
      </div>
    ),
    { ...size }
  );
}
