import type { Metadata } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
import "./globals.css";

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

export const metadata: Metadata = {
  // Prod resolves OG/Twitter image URLs against this — set NEXT_PUBLIC_SITE_URL in deploy.
  metadataBase: new URL(process.env.NEXT_PUBLIC_SITE_URL || "http://localhost:3000"),
  title: {
    default: "ProveKit — Prove any AI agent works",
    template: "%s · ProveKit",
  },
  description:
    "The open-source universal agent client. Test, debug and evaluate any AI agent — LLM, MCP, HTTP or A2A, any provider, no SDK. Turn a run into a regression test and run the suite in CI.",
  keywords: [
    "AI agent testing",
    "MCP testing",
    "agent CI",
    "LLM evals",
    "regression testing agents",
    "prompt testing",
    "OpenAI",
    "Anthropic",
    "A2A",
    "open source",
  ],
  applicationName: "ProveKit",
  openGraph: {
    title: "ProveKit — Prove any AI agent works",
    description:
      "Test any AI agent (LLM/MCP/HTTP/A2A), turn a run into a regression test, run the suite in CI. Open source, runs locally.",
    siteName: "ProveKit",
    type: "website",
  },
  twitter: {
    card: "summary_large_image",
    title: "ProveKit — Prove any AI agent works",
    description:
      "The open-source universal agent client. Test/debug/eval any agent, turn runs into CI regression tests.",
  },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${inter.variable} ${mono.variable}`}>
      <body>{children}</body>
    </html>
  );
}
