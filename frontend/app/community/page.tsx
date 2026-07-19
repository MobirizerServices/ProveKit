import Link from "next/link";
import type { Metadata } from "next";
import TopNav from "@/components/TopNav";

export const metadata: Metadata = {
  title: "Community",
  description: "Get involved with ProveKit — GitHub Discussions, issues, contributing, and the roadmap.",
  alternates: { canonical: "/community" },
};

const REPO = "https://github.com/MobirizerServices/ProveKit";
const CARDS = [
  { t: "GitHub", d: "Star the repo, read the code, and follow releases.", href: REPO, cta: "Open GitHub" },
  { t: "Discussions", d: "Ask questions, share what you're building, and suggest ideas.", href: `${REPO}/discussions`, cta: "Join the discussion" },
  { t: "Issues", d: "Report a bug or request a feature. Good-first-issues welcome.", href: `${REPO}/issues`, cta: "Browse issues" },
  { t: "Contributing", d: "Clone-to-running in minutes; PRs of all sizes are welcome.", href: `${REPO}/blob/main/CONTRIBUTING.md`, cta: "Read the guide" },
  { t: "Changelog", d: "See what shipped in each release.", href: `${REPO}/blob/main/CHANGELOG.md`, cta: "View changelog" },
  { t: "Security", d: "Responsible-disclosure policy and how to report a vulnerability.", href: `${REPO}/blob/main/SECURITY.md`, cta: "Security policy" },
];

export default function CommunityPage() {
  return (
    <>
      <TopNav />
      <main style={{ maxWidth: 860, margin: "0 auto", padding: "28px 20px 80px" }}>
        <h1 style={{ fontSize: 30, letterSpacing: -0.6, margin: "0 0 6px" }}>Community</h1>
        <p className="muted" style={{ margin: "0 0 28px", fontSize: 15 }}>
          ProveKit is open source and built in the open. Here’s how to get involved.
        </p>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: 14 }}>
          {CARDS.map((c) => (
            <a key={c.t} href={c.href} target="_blank" rel="noreferrer"
              style={{ display: "block", padding: 18, borderRadius: 14, border: "1px solid var(--border)", background: "var(--panel)", textDecoration: "none", color: "inherit" }}>
              <div style={{ fontSize: 16, fontWeight: 600, marginBottom: 6 }}>{c.t}</div>
              <div className="muted" style={{ fontSize: 13.5, lineHeight: 1.5, marginBottom: 12 }}>{c.d}</div>
              <span style={{ color: "var(--accent)", fontSize: 13.5 }}>{c.cta} →</span>
            </a>
          ))}
        </div>
        <div style={{ marginTop: 28, textAlign: "center" }}>
          <Link href="/signup" className="btn lp-btn-primary" style={{ padding: "10px 20px" }}>Start tracing your agents</Link>
        </div>
      </main>
    </>
  );
}
