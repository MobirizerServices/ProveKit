import Script from "next/script";

// Privacy-friendly, cookie-free analytics — off unless NEXT_PUBLIC_PLAUSIBLE_DOMAIN is set at
// build/deploy time. Self-hosters can point NEXT_PUBLIC_PLAUSIBLE_SRC at their own instance.
export default function Analytics() {
  const domain = process.env.NEXT_PUBLIC_PLAUSIBLE_DOMAIN;
  if (!domain) return null;
  const src = process.env.NEXT_PUBLIC_PLAUSIBLE_SRC || "https://plausible.io/js/script.js";
  return <Script defer data-domain={domain} src={src} strategy="afterInteractive" />;
}
