import type { Metadata } from "next";
import Markdown from "@/components/Markdown";
import TopNav from "@/components/TopNav";

export const metadata: Metadata = {
  title: "Privacy Policy",
  description: "How ProveKit handles data. ProveKit is self-hostable — you run it and own your data.",
  alternates: { canonical: "/privacy" },
};

const BODY = `ProveKit is open-source software you run yourself. This page describes how data is
handled; if you self-host, **you** are the data controller and this reflects the software's
default behavior.

## What ProveKit stores

When you use tracing, the SDK sends the inputs, outputs, timing, token usage, and logs of the
runs you instrument to the ProveKit instance you configured (via \`PROVEKIT_ENDPOINT\`). Those
traces are stored in **your** database on **your** infrastructure.

## Your model keys

ProveKit never asks for or stores your OpenAI/Anthropic keys — those stay in your agent's
environment. Your project key (\`pk_...\`) authenticates trace ingest and is stored hashed.

## PII

Traces can contain personal data if your agent's inputs/outputs do. ProveKit provides an
optional **PII masking** setting that redacts emails, card numbers, and secrets on ingest,
plus configurable retention so old data is pruned automatically.

## The hosted option

If you use a hosted ProveKit deployment operated by a third party, that operator's privacy
policy governs your data. This default policy applies to self-hosted installs.

## Contact

Questions or a data request? Open an issue on
[GitHub](https://github.com/MobirizerServices/ProveKit/issues).

_This is a template for an open-source project and not legal advice. Consult a professional
for your jurisdiction before relying on it in production._`;

export default function PrivacyPage() {
  return (
    <>
      <TopNav />
      <main style={{ maxWidth: 720, margin: "0 auto", padding: "28px 20px 80px" }}>
        <h1 style={{ fontSize: 30, letterSpacing: -0.6, margin: "0 0 20px" }}>Privacy Policy</h1>
        <Markdown source={BODY} />
      </main>
    </>
  );
}
