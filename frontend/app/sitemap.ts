import type { MetadataRoute } from "next";
import { POSTS } from "@/lib/posts";

const SITE = process.env.NEXT_PUBLIC_SITE_URL || "http://localhost:3000";

export default function sitemap(): MetadataRoute.Sitemap {
  const staticPages = [
    { url: "/", priority: 1.0 },
    { url: "/blog", priority: 0.8 },
    { url: "/community", priority: 0.5 },
    { url: "/login", priority: 0.3 },
    { url: "/signup", priority: 0.5 },
    { url: "/privacy", priority: 0.2 },
    { url: "/terms", priority: 0.2 },
  ].map((p) => ({ url: `${SITE}${p.url}`, changeFrequency: "weekly" as const, priority: p.priority }));

  const posts = POSTS.map((p) => ({
    url: `${SITE}/blog/${p.slug}`,
    lastModified: new Date(p.date),
    changeFrequency: "monthly" as const,
    priority: 0.6,
  }));

  return [...staticPages, ...posts];
}
