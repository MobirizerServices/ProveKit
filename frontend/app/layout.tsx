import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import Analytics from "@/components/Analytics";

const sans = Geist({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-sans",
});
const mono = Geist_Mono({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-mono",
});

const DESC =
  "Design, trace, replay, and evaluate every agent decision in one reliability workspace — " +
  "without stitching together five different tools. OpenTelemetry native, self-host ready.";

export const metadata: Metadata = {
  // Prod resolves OG/Twitter image URLs against this — set NEXT_PUBLIC_SITE_URL in deploy.
  metadataBase: new URL(process.env.NEXT_PUBLIC_SITE_URL || "http://localhost:3000"),
  title: {
    default: "ProveKit — Build agents. Prove they work.",
    template: "%s · ProveKit",
  },
  description: DESC,
  keywords: [
    "AI agent observability",
    "AI reliability workspace",
    "LLM tracing",
    "agent tracing",
    "deterministic replay",
    "LLM evaluations",
    "prompt registry",
    "LangChain tracing",
    "OpenTelemetry LLM",
    "CI regression gate",
    "OpenAI",
    "Anthropic",
    "open source",
    "self-hosted",
  ],
  applicationName: "ProveKit",
  authors: [{ name: "ProveKit" }],
  openGraph: {
    title: "ProveKit — Build agents. Prove they work.",
    description: DESC,
    siteName: "ProveKit",
    type: "website",
    url: "/",
  },
  twitter: {
    card: "summary_large_image",
    title: "ProveKit — Build agents. Prove they work.",
    description:
      "The evidence layer for production AI. Trace → replay → evaluate every agent decision in one reliability workspace.",
  },
  alternates: { canonical: "/" },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${sans.variable} ${mono.variable}`}>
      <body>
        <a href="#main" className="skip-link">Skip to content</a>
        <div id="main">{children}</div>
        <Analytics />
      </body>
    </html>
  );
}
