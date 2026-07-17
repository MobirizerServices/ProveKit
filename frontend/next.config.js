/** @type {import('next').NextConfig} */
// In dev (and any same-origin deploy) the browser calls /api and /v1 on this origin;
// these rewrites forward them to the backend so cookies stay first-party and no CORS is
// needed. Prod behind a reverse proxy can route /api + /v1 the same way.
const API_TARGET = process.env.API_PROXY_TARGET || "http://localhost:8100";

const nextConfig = {
  reactStrictMode: true,
  output: "standalone", // slim container image; ignored by `next dev`
  async rewrites() {
    // If NEXT_PUBLIC_API_BASE is set the client calls the backend directly (split domain),
    // so skip the proxy.
    if (process.env.NEXT_PUBLIC_API_BASE) return [];
    return [
      { source: "/api/:path*", destination: `${API_TARGET}/api/:path*` },
      { source: "/v1/:path*", destination: `${API_TARGET}/v1/:path*` },
      { source: "/healthz", destination: `${API_TARGET}/healthz` },  // TopNav health poll
    ];
  },
};
module.exports = nextConfig;
