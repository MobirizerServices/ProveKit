import type { Metadata } from "next";
import Markdown from "@/components/Markdown";
import TopNav from "@/components/TopNav";

export const metadata: Metadata = {
  title: "Terms",
  description: "Terms for using ProveKit, an open-source, self-hostable agent observability tool.",
  alternates: { canonical: "/terms" },
};

const BODY = `ProveKit is open-source software. Your use of the source code is governed by the
license in the repository; this page covers using a ProveKit deployment.

## The software is provided "as is"

ProveKit is provided without warranty of any kind. To the maximum extent permitted by law, the
authors are not liable for any damages arising from its use. You are responsible for how you
deploy and operate it.

## Acceptable use

Don't use ProveKit to break the law, infringe others' rights, or process data you have no
right to process. If you invite members to a project, you're responsible for their access.

## Your content

You retain all rights to the traces, datasets, and other content you store in your ProveKit
instance. The software does not claim any license over your data.

## The hosted option

If you use a hosted ProveKit deployment operated by a third party, that operator's terms apply
in addition to these.

## Changes

As an open-source project, these terms may change with new releases. The version in the
repository at the time of your deployment applies.

_This is a template for an open-source project and not legal advice._`;

export default function TermsPage() {
  return (
    <>
      <TopNav />
      <main style={{ maxWidth: 720, margin: "0 auto", padding: "28px 20px 80px" }}>
        <h1 style={{ fontSize: 30, letterSpacing: -0.6, margin: "0 0 20px" }}>Terms</h1>
        <Markdown source={BODY} />
      </main>
    </>
  );
}
