# Landing page — 100 points to production-ready

A concrete checklist to take the ProveKit landing from "clean MVP" to a marketing site that
converts, ranks, and supports a community. Grouped by area; each is actionable. Tags:
🔴 do-before-launch · 🟡 high-leverage · 🟢 later.

> The current landing has: hero + trace-preview card, an animated agent-flow graph, a code
> band, a feature grid, quickstart steps, and CTAs to `/signup` · `/login`. These build on that.

## A. Content & messaging (1–10)
1. 🔴 Sharpen the one-line value prop and A/B test 2–3 variants of the hero headline.
2. 🔴 Add a sub-30-word "what is ProveKit" sentence above the fold for cold visitors.
3. 🟡 Add an "outcomes" strip: *find failures faster · cut token spend · ship with a CI gate*.
4. 🟡 Add a "who it's for" line (AI engineers building agents on OpenAI/Anthropic/LangChain).
5. 🟡 Add a short "why not just logs / LangSmith / Langfuse" positioning paragraph or table.
6. 🟢 Add an FAQ section (self-host? data privacy? which frameworks? pricing? OSS license?).
7. 🟢 Add a "what you get in 2 minutes" checklist near the quickstart.
8. 🟢 Write microcopy for empty/hover states and button labels (verbs, not nouns).
9. 🟢 Add a one-line changelog/"what's new" teaser linking to the CHANGELOG.
10. 🟢 Localize copy tone for developers — concrete, no fluff, show the code early (done).

## B. Social proof & trust (11–20)
11. 🔴 Add a GitHub star count + "star on GitHub" button (live badge).
12. 🟡 Add a logos strip ("works with") for OpenAI, Anthropic, LangChain, LlamaIndex, CrewAI.
13. 🟡 Add 2–3 testimonial quotes (even from early users / your own) with name + role + avatar.
14. 🟡 Add a "trusted by N teams / M traces captured" metric once you have numbers.
15. 🟢 Add a case study / "how X debugged their agent" once available.
16. 🟢 Show a security posture badge (self-hosted, your keys, PII redaction, no data leaves).
17. 🟢 Add a "backed by / featured on" strip (HN, Product Hunt, newsletters) after launch.
18. 🟢 Link a public roadmap (GitHub Projects) to signal momentum.
19. 🟢 Add contributor avatars / "N contributors" from the repo.
20. 🟢 Add an uptime/status page link for the hosted option (if offered).

## C. Conversion & CTAs (21–30)
21. 🔴 Ensure a single, obvious primary CTA above the fold (Get started → /signup) (done).
22. 🔴 Add a sticky top-nav CTA that persists on scroll (done — make it more prominent).
23. 🟡 Add a secondary "Live demo / sandbox" CTA that needs no signup.
24. 🟡 Add a repeated CTA after each major section (mid-page + final) (final done).
25. 🟡 Offer "Deploy in 1 command" / Docker copy-button as a low-friction path.
26. 🟢 Add "Book a demo" / Cal.com link for team/enterprise leads.
27. 🟢 Add exit-intent or scroll-depth CTA (email capture) — tastefully.
28. 🟢 Add a newsletter signup ("get launch + tips") wired to an ESP.
29. 🟢 Show social login options on /signup (GitHub OAuth) to cut friction.
30. 🟢 Add a "no credit card, open source" reassurance under the CTA.

## D. Visuals & interactive demo (31–40)
31. 🔴 Replace static preview with a short autoplaying, muted product GIF/video loop.
32. 🟡 Make the agent-flow graph interactive (hover a node → tooltip) (static SVG today).
33. 🟡 Add a live "public sandbox" trace users can click through without an account.
34. 🟡 Add before/after: raw logs vs the ProveKit flow graph.
35. 🟢 Add a short (30–60s) narrated demo video with captions.
36. 🟢 Add a screenshot carousel: Flow, Waterfall, Dashboard, Evaluation.
37. 🟢 Add an animated "one decorator → nested flow" scrollytelling moment.
38. 🟢 Add a dark/light preview toggle for the visuals.
39. 🟢 Generate a proper OG/Twitter card image (1200×630) per page.
40. 🟢 Add a favicon set + apple-touch-icon + web manifest (PWA-ready).

## E. Blog & content marketing (41–52)
41. 🔴 Add a `/blog` with an index + individual post routes (MDX or a headless CMS).
42. 🔴 Ship 3 launch posts: "Introducing ProveKit", "Tracing an agent in one line", "Eval gates in CI".
43. 🟡 Add author profiles, publish dates, reading time, and tags to posts.
44. 🟡 Add an RSS/Atom feed and JSON feed for the blog.
45. 🟡 Add per-post OG images (auto-generated via a template).
46. 🟡 Add "How we built X" engineering posts (OTel exporter, MCP server) for developer SEO.
47. 🟢 Add tutorial series: LangChain, CrewAI, LlamaIndex, raw OpenAI — each a post + example.
48. 🟢 Add a "comparisons" pillar page (vs LangSmith/Langfuse/Phoenix) — high-intent SEO.
49. 🟢 Add code-copy buttons and syntax highlighting in posts.
50. 🟢 Add related-posts and a newsletter CTA at the end of each post.
51. 🟢 Add canonical tags + social share buttons per post.
52. 🟢 Cross-post to dev.to / Hashnode / Medium with canonical back to your blog.

## F. Community (53–62)
53. 🔴 Add prominent links to GitHub Discussions and/or a Discord/Slack community.
54. 🔴 Add a `CONTRIBUTING.md` link + "good first issue" label and surface it on the site.
55. 🟡 Add a community page: Discord invite, Discussions, office hours, roadmap.
56. 🟡 Add a "Show & tell" / showcase gallery of agents traced with ProveKit.
57. 🟡 Add issue/PR templates and a CODE_OF_CONDUCT to lower the contribution barrier.
58. 🟢 Add a public changelog page (not just CHANGELOG.md) with subscribe.
59. 🟢 Start a "community spotlight" in the blog/newsletter.
60. 🟢 Add a Discord widget or member count to the community page.
61. 🟢 Host the docs as a searchable site (Docusaurus/Mintlify) linked from nav.
62. 🟢 Add a "star history" chart to show growth.

## G. SEO & discoverability (63–74)
63. 🔴 Add per-page `<title>` + meta description (unique, keyword-aware) via Next metadata.
64. 🔴 Add Open Graph + Twitter Card meta tags site-wide.
65. 🔴 Add `robots.txt` and a generated `sitemap.xml` (Next `sitemap.ts`).
66. 🟡 Add JSON-LD structured data (SoftwareApplication, Organization, FAQPage, Article).
67. 🟡 Ensure semantic HTML (one h1, logical h2/h3, landmark regions).
68. 🟡 Add descriptive alt text to every image/visual (the flow graph has an aria-label — extend).
69. 🟡 Target keyword clusters: "LLM agent observability", "trace AI agent", "LangChain tracing".
70. 🟢 Add a canonical URL per page; handle trailing-slash + www consistently.
71. 🟢 Pre-render/SSG the landing and blog for crawlability (avoid client-only content).
72. 🟢 Submit sitemap to Google Search Console + Bing Webmaster; monitor coverage.
73. 🟢 Build internal links between blog ↔ docs ↔ landing sections.
74. 🟢 Add hreflang tags if/when localized.

## H. Performance & Core Web Vitals (75–82)
75. 🔴 Hit green Core Web Vitals (LCP < 2.5s, CLS < 0.1, INP < 200ms) — measure with Lighthouse.
76. 🔴 Preload the hero font; use `font-display: swap`; subset fonts.
77. 🟡 Convert images to AVIF/WebP with `next/image`, correct sizes + lazy loading.
78. 🟡 Inline critical CSS; defer non-critical; drop unused CSS.
79. 🟡 Reserve space for the hero visual to avoid layout shift (fixed aspect) (SVG helps).
80. 🟢 Self-host fonts/assets (no third-party render-blocking requests).
81. 🟢 Respect `prefers-reduced-motion` for all animations (edges already do).
82. 🟢 Add a CDN + long-cache headers for static assets.

## I. Accessibility (83–88)
83. 🔴 Keyboard-navigable nav, CTAs, and the mobile menu; visible focus rings.
84. 🔴 Color-contrast AA for text on the dark theme (audit the muted greys).
85. 🟡 Proper labels/roles for interactive elements; skip-to-content link.
86. 🟡 Alt text / aria for decorative vs meaningful graphics.
87. 🟢 Test with a screen reader (VoiceOver/NVDA) and fix reading order.
88. 🟢 Ensure the animated flow doesn't trigger motion sickness (reduced-motion done).

## J. Analytics, experimentation & ops (89–94)
89. 🔴 Add privacy-friendly analytics (Plausible/PostHog) with cookie-free defaults.
90. 🟡 Track funnel events: hero CTA → /signup → activated (first trace).
91. 🟡 Add an A/B testing harness (PostHog flags) for headline/CTA experiments.
92. 🟢 Add error monitoring for the marketing site (already have Sentry in the app).
93. 🟢 Add UTM handling + attribution for campaigns.
94. 🟢 Add a lightweight consent banner only where legally required (avoid dark patterns).

## K. Legal, footer & polish (95–100)
95. 🔴 Add a real footer: Product, Docs, Blog, Community, GitHub, Privacy, Terms, License.
96. 🔴 Add Privacy Policy + Terms pages (self-host + hosted variants).
97. 🟡 Add a security/responsible-disclosure link (SECURITY.md) in the footer.
98. 🟡 Add a mobile hamburger menu (nav links currently hide < 820px).
99. 🟢 Add a 404 and error page with a friendly CTA back to /.
100. 🟢 Final QA pass: real device testing (iOS/Android), link check, spellcheck, print styles.

---

### Suggested first sprint (the 🔴 set, ordered by impact)
1. SEO metadata + OG cards + sitemap/robots (63–65) — cheap, compounding.
2. `/blog` with the 3 launch posts (41–42) — the top of the funnel.
3. GitHub stars + logos + testimonials (11–13) — trust above the fold.
4. Product GIF/video loop replacing the static preview (31).
5. Footer + Privacy/Terms (95–96) and community links (53) — credibility + legal.
6. Analytics + funnel events (89–90) — so every later change is measurable.

Everything past the 🔴 set is a backlog to pull from once you're live and measuring — don't
block launch on the full 100.
