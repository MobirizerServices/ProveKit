import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

// Gate the authed portal behind login in HOSTED deployments: if there's no session cookie,
// redirect to /login before the page renders (no flash). In local/self-host mode (HOSTED
// unset) the backend auto-uses the built-in local user, so we leave the portal open.
const HOSTED = process.env.HOSTED === "true";
const SESSION_COOKIE = "agm_session";

export function middleware(req: NextRequest) {
  if (!HOSTED) return NextResponse.next();
  if (req.cookies.get(SESSION_COOKIE)) return NextResponse.next();
  const url = req.nextUrl.clone();
  url.pathname = "/login";
  url.searchParams.set("next", req.nextUrl.pathname);
  return NextResponse.redirect(url);
}

// Only the authed portal routes are protected; marketing/content/auth pages stay public.
export const config = {
  matcher: [
    "/traces/:path*",
    "/flows/:path*",
    "/replay/:path*",
    "/experiments/:path*",
    "/dashboard/:path*",
    "/datasets/:path*",
    "/admin/:path*",
    "/settings/:path*",
    "/api-keys/:path*",
  ],
};
