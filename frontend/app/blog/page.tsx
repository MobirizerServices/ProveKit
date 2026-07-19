import Link from "next/link";
import type { Metadata } from "next";
import { POSTS } from "@/lib/posts";
import TopNav from "@/components/TopNav";

export const metadata: Metadata = {
  title: "Blog",
  description: "Guides and updates on tracing, evaluating, and shipping AI agents with ProveKit.",
  alternates: { canonical: "/blog" },
};

function fmt(d: string) {
  return new Date(d).toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" });
}

export default function BlogIndex() {
  const posts = [...POSTS].sort((a, b) => (a.date < b.date ? 1 : -1));
  return (
    <>
      <TopNav />
      <main style={{ maxWidth: 760, margin: "0 auto", padding: "28px 20px 80px" }}>
        <h1 style={{ fontSize: 30, letterSpacing: -0.6, margin: "0 0 6px" }}>Blog</h1>
        <p className="muted" style={{ margin: "0 0 28px", fontSize: 15 }}>
          Guides and updates on tracing, evaluating, and shipping AI agents.
        </p>
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          {posts.map((p) => (
            <Link key={p.slug} href={`/blog/${p.slug}`} className="blog-item">
              <div className="blog-item-meta">{fmt(p.date)} · {p.minutes} min read · {p.tags.join(" · ")}</div>
              <div className="blog-item-title">{p.title}</div>
              <div className="blog-item-desc">{p.description}</div>
            </Link>
          ))}
        </div>
      </main>
    </>
  );
}
