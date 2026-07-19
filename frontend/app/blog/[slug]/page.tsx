import Link from "next/link";
import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { getPost, POSTS } from "@/lib/posts";
import Markdown from "@/components/Markdown";
import TopNav from "@/components/TopNav";

export function generateStaticParams() {
  return POSTS.map((p) => ({ slug: p.slug }));
}

export async function generateMetadata({ params }: { params: Promise<{ slug: string }> }): Promise<Metadata> {
  const { slug } = await params;
  const post = getPost(slug);
  if (!post) return {};
  return {
    title: post.title,
    description: post.description,
    alternates: { canonical: `/blog/${post.slug}` },
    openGraph: { title: post.title, description: post.description, type: "article",
      publishedTime: post.date, url: `/blog/${post.slug}` },
    twitter: { card: "summary_large_image", title: post.title, description: post.description },
  };
}

function fmt(d: string) {
  return new Date(d).toLocaleDateString("en-US", { year: "numeric", month: "long", day: "numeric" });
}

export default async function BlogPost({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const post = getPost(slug);
  if (!post) notFound();

  const ld = {
    "@context": "https://schema.org", "@type": "BlogPosting",
    headline: post.title, description: post.description, datePublished: post.date,
    author: { "@type": "Organization", name: post.author },
    publisher: { "@type": "Organization", name: "ProveKit" },
  };

  return (
    <>
      <TopNav />
      <main style={{ maxWidth: 720, margin: "0 auto", padding: "28px 20px 90px" }}>
        <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(ld) }} />
        <Link href="/blog" className="md-link" style={{ fontSize: 13.5 }}>← All posts</Link>
        <h1 style={{ fontSize: 34, letterSpacing: -0.8, lineHeight: 1.12, margin: "14px 0 10px" }}>{post.title}</h1>
        <div className="muted" style={{ fontSize: 13.5, marginBottom: 26 }}>
          {fmt(post.date)} · {post.minutes} min read · {post.author}
        </div>
        <article><Markdown source={post.body} /></article>
        <div className="blog-cta">
          <div style={{ fontSize: 16, fontWeight: 600, marginBottom: 6 }}>See what your agent is doing.</div>
          <div className="muted" style={{ fontSize: 14, marginBottom: 14 }}>Add one decorator and get the whole flow — open source, self-hostable.</div>
          <Link href="/signup" className="btn lp-btn-primary" style={{ padding: "10px 20px" }}>Get started free</Link>
        </div>
      </main>
    </>
  );
}
