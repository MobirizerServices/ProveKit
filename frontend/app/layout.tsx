import type { Metadata } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
import "./globals.css";
import Analytics from "@/components/Analytics";

const inter = Inter({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-sans",
  axes: ["opsz"],
});
const mono = JetBrains_Mono({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-mono",
  weight: ["400", "500", "600", "700"],
});

const DESC =
  "Drop-in tracing for any AI agent. Add one decorator and see every run your agent makes — " +
  "model calls, tools, retries, the whole nested flow — then evaluate it, watch it, and gate " +
  "your CI on it. Open source and self-hostable.";

export const metadata: Metadata = {
  // Prod resolves OG/Twitter image URLs against this — set NEXT_PUBLIC_SITE_URL in deploy.
  metadataBase: new URL(process.env.NEXT_PUBLIC_SITE_URL || "http://localhost:3000"),
  title: {
    default: "ProveKit — See exactly what your AI agent did",
    template: "%s · ProveKit",
  },
  description: DESC,
  keywords: [
    "AI agent observability",
    "LLM tracing",
    "agent tracing",
    "LangChain tracing",
    "OpenTelemetry LLM",
    "LLM evals",
    "agent evaluation",
    "CI regression gate",
    "OpenAI",
    "Anthropic",
    "open source",
    "self-hosted",
  ],
  applicationName: "ProveKit",
  authors: [{ name: "ProveKit" }],
  openGraph: {
    title: "ProveKit — See exactly what your AI agent did",
    description: DESC,
    siteName: "ProveKit",
    type: "website",
    url: "/",
  },
  twitter: {
    card: "summary_large_image",
    title: "ProveKit — See exactly what your AI agent did",
    description:
      "Drop-in tracing for any AI agent — one decorator, the whole nested flow, plus evals, dashboards, and a CI gate. Open source, self-hostable.",
  },
  alternates: { canonical: "/" },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${inter.variable} ${mono.variable}`}>
      <body>
        <a href="#main" className="skip-link">Skip to content</a>
        <div id="main">{children}</div>
        <Analytics />
      </body>
    </html>
  );
}
