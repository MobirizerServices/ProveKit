import type { MetadataRoute } from "next";

const SITE = process.env.NEXT_PUBLIC_SITE_URL || "http://localhost:3000";

export default function robots(): MetadataRoute.Robots {
  return {
    rules: {
      userAgent: "*",
      allow: "/",
      // Keep the authed app out of the index — only marketing/content pages should rank.
      disallow: ["/traces", "/dashboard", "/datasets", "/admin", "/settings", "/api-keys", "/shared/"],
    },
    sitemap: `${SITE}/sitemap.xml`,
  };
}
