import Link from "next/link";

export default function NotFound() {
  return (
    <main style={{ minHeight: "80vh", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", textAlign: "center", padding: "40px 20px", gap: 14 }}>
      <div style={{ fontSize: 15, fontWeight: 600 }}><span style={{ color: "var(--accent)" }}>◇</span> ProveKit</div>
      <div style={{ fontSize: 56, fontWeight: 800, letterSpacing: -1 }}>404</div>
      <p className="muted" style={{ fontSize: 15, maxWidth: 420 }}>That page doesn’t exist. It may have moved, or the link was mistyped.</p>
      <div style={{ display: "flex", gap: 12, marginTop: 6 }}>
        <Link href="/" className="btn lp-btn-primary" style={{ padding: "10px 20px" }}>Home</Link>
        <Link href="/blog" className="btn btn-ghost" style={{ padding: "10px 20px" }}>Blog</Link>
      </div>
    </main>
  );
}
