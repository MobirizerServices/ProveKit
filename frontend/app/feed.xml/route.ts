import { POSTS } from "@/lib/posts";

const SITE = process.env.NEXT_PUBLIC_SITE_URL || "http://localhost:3000";

function esc(s: string) {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

export async function GET() {
  const items = [...POSTS]
    .sort((a, b) => (a.date < b.date ? 1 : -1))
    .map((p) => `    <item>
      <title>${esc(p.title)}</title>
      <link>${SITE}/blog/${p.slug}</link>
      <guid>${SITE}/blog/${p.slug}</guid>
      <pubDate>${new Date(p.date).toUTCString()}</pubDate>
      <description>${esc(p.description)}</description>
    </item>`).join("\n");

  const xml = `<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>ProveKit Blog</title>
    <link>${SITE}/blog</link>
    <description>Guides and updates on tracing, evaluating, and shipping AI agents.</description>
${items}
  </channel>
</rss>`;

  return new Response(xml, { headers: { "Content-Type": "application/rss+xml; charset=utf-8" } });
}
