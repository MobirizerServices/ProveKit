# ProveKit UI — 200 points to world-class & production-ready

A concrete, prioritized checklist to take the portal from "functional" to "world-class."
Tags — Impact: 🔴 must-have · 🟡 high-value · 🟢 polish. Effort: S (hours) · M (1–2 days) · L (bigger).

> **Reality check (kept honest):** this is a *menu to pull from*, not a build-all-before-launch
> list. The product is live and works. Ship, get real users, and let their traces tell you
> which 30 of these 200 actually matter. The two visible bugs (#41, #16) are the only true
> "fix now" items.

---

## 1. Trace list & navigation (1–10)
1. 🔴 Server-side pagination / infinite scroll — the list can't render thousands of rows. **M**
2. 🔴 Show status + error badge on each row (red dot exists; add the error reason on hover). **S**
3. 🔴 Cost per trace in the row (tokens already shown). **S**
4. 🟡 Sortable columns: time, latency, tokens, cost, status. **M**
5. 🟡 Column/list density toggle (comfortable / compact). **S**
6. 🟡 Group rows by agent name with per-agent counts. **M**
7. 🟡 Relative timestamps ("2m ago") with absolute on hover — all rows currently show identical clock time. **S**
8. 🟢 Keyboard nav (↑/↓ to move, Enter to open, / to focus filter). **M**
9. 🟢 Row hover preview (mini flow thumbnail). **M**
10. 🟢 "New traces" live indicator + auto-prepend without losing your place. **M**

## 2. Flow graph / node view (11–20)
11. 🔴 Auto-layout with dagre for wide/deep trees (current layout overlaps at scale). **M**
12. 🔴 Node status ring/icon (✓ / ✕ / ⚠) — failures should read at a glance. **S**
13. 🟡 Collapse/expand a subtree; aggregate repeated steps into one node with a counter. **M**
14. 🟡 Critical-path highlight (longest dependency chain). **M**
15. 🟡 Focus mode — dim everything not on the selected node's path. **S**
16. 🔴 Fix the empty black **minimap** for small graphs (hide < ~8 nodes, or fit-to-content). **S**
17. 🟡 Fit-to-selection button + "reset view". **S**
18. 🟢 Export the graph as PNG/SVG. **S**
19. 🟢 Animate nodes appearing as a live trace streams in. **M**
20. 🟢 Edge labels ("calls" / "returns") and hover tooltips with quick stats. **S**

## 3. Waterfall / timeline (21–30)
21. 🔴 Shared timeline axis with tick labels (ms/s marks). **M**
22. 🟡 Show idle/gap time between spans. **S**
23. 🟡 Color bars by span type + status (failed = red) consistently. **S**
24. 🟡 Collapse/expand nested rows; sticky parent while scrolling. **M**
25. 🟡 Hover a bar → tooltip with start offset, duration, tokens. **S**
26. 🟢 Zoom into a time window (brush select). **M**
27. 🟢 Latency percentile context ("p95 for this span type"). **M**
28. 🟢 Virtualize rows for 1000+ span traces. **M**
29. 🟢 Jump-to-span from the waterfall into the flow graph and back. **S**
30. 🟢 "Slowest span" and "most expensive span" quick markers. **S**

## 4. Span detail panel (31–40)
31. 🔴 Render LLM input/output as a **chat transcript** (roles), not raw text — the single biggest "feels pro" win. **M**
32. 🔴 Show invocation params (temperature, top_p, max_tokens) and finish_reason clearly. **S**
33. 🟡 Syntax-highlight + collapse long JSON payloads with "show more". **S**
34. 🟡 Copy buttons on input / output / span id / trace id. **S**
35. 🟡 Tool spans: show tool name, arguments, and result distinctly. **M**
36. 🟡 Retriever spans: show retrieved chunks + relevance scores + embedding model. **M**
37. 🟡 Show the exception + stack trace on failed spans (not just a red dot). **S**
38. 🟢 A "logs" tab per span with level filter. **S**
39. 🟢 Raw-attributes inspector (every captured OTel attribute). **S**
40. 🟢 Jump-to-parent / jump-to-children links. **S**

## 5. Cost, tokens & usage (41–50)
41. 🔴 **Fix `~$0.0000`** — show `<$0.01` (or `—`) for sub-cent, full precision on hover. **S**
42. 🔴 Maintain a real, updatable model price table (don't hardcode). **M**
43. 🟡 Per-model cost breakdown within a trace. **S**
44. 🟡 Cache-hit / cached-token accounting (providers report it). **M**
45. 🟡 Reasoning-token handling (o-series) in cost. **S**
46. 🟡 Currency selector + configurable rates. **S**
47. 🟢 Cost/token heat coloring on nodes. **S**
48. 🟢 "Most expensive traces" leaderboard. **M**
49. 🟢 Budget indicator ("$X of $Y this month"). **M**
50. 🟢 Show tokens/sec and cost/1k-tokens efficiency metrics. **S**

## 6. Dashboard & analytics (51–60)
51. 🔴 Real charts (a lightweight chart lib) for latency/error/tokens over time, not just bars. **M**
52. 🔴 Time-range picker synced across the dashboard (24h / 7d / 30d / custom). **M**
53. 🟡 Error-rate trend line with the current vs previous period delta. **S**
54. 🟡 Latency histogram + p50/p90/p95/p99. **M**
55. 🟡 Throughput (traces/min) and token-rate charts. **M**
56. 🟡 Per-agent / per-model filter on the whole dashboard. **M**
57. 🟢 Custom dashboards (pin the charts you care about). **L**
58. 🟢 Anomaly markers on the timeline (latency/cost spikes). **M**
59. 🟢 Comparison mode (this week vs last). **M**
60. 🟢 Export dashboard as PNG/PDF for a report. **S**

## 7. Search, filter & query (61–70)
61. 🔴 Filter by status / model / agent / time / tokens / cost (not just text). **M**
62. 🔴 Full-text search over inputs & outputs. **L**
63. 🟡 Saved views / saved filters. **M**
64. 🟡 URL-encoded filters (shareable, back-button friendly). **S**
65. 🟡 Filter chips that show what's active + one-click clear. **S**
66. 🟡 "Failed only" and "slow (>p95)" quick filters. **S**
67. 🟢 A query language / structured filter builder for power users. **L**
68. 🟢 Search history + suggestions. **S**
69. 🟢 Filter by session / user / tag. **M**
70. 🟢 Regex / exact-match toggle in search. **S**

## 8. Sessions, threads & grouping (71–80)
71. 🔴 Group multi-turn runs by session id (a conversation view). **M**
72. 🟡 Session detail: turns in order, cumulative tokens/cost, duration. **M**
73. 🟡 Session badge already on rows — make it a filter and a drill-in. **S**
74. 🟡 User-id dimension (tag traces by end-user). **M**
75. 🟢 Thread/branch visualization for agent handoffs. **L**
76. 🟢 "Replay conversation" as a chat transcript. **M**
77. 🟢 Session-level feedback/score rollup. **M**
78. 🟢 Group by trace name to see aggregate stats per agent. **M**
79. 🟢 Tags: add/edit tags on a trace, filter by them. **M**
80. 🟢 Environment dimension (dev / staging / prod) as a first-class filter. **S**

## 9. Evaluation & datasets UI (81–90)
81. 🔴 "Add to dataset" from a trace/span (one click). **M**
82. 🔴 Dataset item editor (input / expected / metadata). **M**
83. 🟡 Run an experiment from the UI (pick dataset + scorers). **L**
84. 🟡 Experiment comparison view (scores across runs, side by side). **M**
85. 🟡 Per-item results table with pass/fail and the scorer breakdown. **M**
86. 🟡 Score distribution charts per experiment. **M**
87. 🟢 Human annotation queue (thumbs + rubric) with keyboard flow. **L**
88. 🟢 Pairwise comparison (A/B two runs). **M**
89. 🟢 LLM-as-judge scorer configuration UI. **L**
90. 🟢 Prompt playground (edit prompt → run against a dataset). **L**

## 10. Real-time & live streaming (91–100)
91. 🔴 Live-update the trace list as new runs arrive (poll or SSE). **M**
92. 🟡 Live span streaming within an open trace (watch it build). **L**
93. 🟡 "Following live" mode with a pause toggle. **S**
94. 🟡 Toast when a trace fails while you're watching. **S**
95. 🟢 Real-time dashboard counters. **M**
96. 🟢 WebSocket transport for low-latency updates. **L**
97. 🟢 Sound/desktop notification on error spikes (opt-in). **S**
98. 🟢 "N new since you loaded" pill. **S**
99. 🟢 Optimistic UI for feedback/score actions. **S**
100. 🟢 Connection-status indicator (live / reconnecting). **S**

## 11. Collaboration & sharing (101–110)
101. 🔴 Shareable read-only trace link (exists) — add expiry + revoke controls. **M**
102. 🟡 Comments/annotations on a trace or span, with @mentions. **L**
103. 🟡 Copy-as-permalink to a specific span. **S**
104. 🟡 "Assign / follow" a failing trace for triage. **M**
105. 🟢 Slack/Teams share (send a trace summary). **M**
106. 🟢 Embeddable trace widget (iframe) for docs/dashboards. **M**
107. 🟢 Activity feed (who viewed/commented). **M**
108. 🟢 Export a trace as JSON / OTLP / shareable HTML. **S**
109. 🟢 Bulk select → add to dataset / export / delete. **M**
110. 🟢 Team presence (who's looking at this trace now). **L**

## 12. Onboarding & empty states (111–120)
111. 🔴 First-run empty state with a copy-paste snippet per framework (exists — extend). **S**
112. 🔴 "Waiting for your first trace" that auto-advances the moment one lands. **S**
113. 🟡 A `provekit doctor` result surfaced in-app (env + connectivity check). **M**
114. 🟡 Interactive product tour (highlight Traces → Dashboard → Datasets). **M**
115. 🟡 Sample/demo project a new user can explore before instrumenting. **M**
116. 🟢 Contextual empty states everywhere (no datasets yet → "create one"). **S**
117. 🟢 Checklist widget ("connect SDK ✓, first trace ✓, first eval ☐"). **M**
118. 🟢 Inline docs links from every screen. **S**
119. 🟢 Framework-detection hint ("we see LangChain spans — here's what's captured"). **M**
120. 🟢 Celebratory moment on the first trace / first eval. **S**

## 13. Design system & visual polish (121–130)
121. 🔴 A proper design-token system (spacing, radius, color scales) — consistency across pages. **M**
122. 🔴 Loading skeletons instead of "Loading…" text. **S**
123. 🟡 Consistent iconography (an icon set, not emoji/glyph mix). **M**
124. 🟡 Light theme (currently dark-only) + a theme toggle. **M**
125. 🟡 Refined type scale + tighter vertical rhythm. **S**
126. 🟡 Consistent card/panel styling and elevation. **S**
127. 🟢 Illustration/empty-state art (branded, not generic). **M**
128. 🟢 A polished favicon set + app icons (partly done). **S**
129. 🟢 Better color-blind-safe status palette. **S**
130. 🟢 Print stylesheet for trace reports. **S**

## 14. Motion & micro-interactions (131–140)
131. 🟡 Smooth panel/route transitions (no hard cuts). **S**
132. 🟡 Animated number counters on the dashboard. **S**
133. 🟡 Hover/press states on every interactive element. **S**
134. 🟡 Graph edges animate along the execution path (partly done) — extend to waterfall. **S**
135. 🟢 Skeleton → content crossfade. **S**
136. 🟢 Subtle confetti/checkmark on success actions. **S**
137. 🟢 Drag feedback when reordering/panning. **S**
138. 🟢 `prefers-reduced-motion` respected everywhere (partly done). **S**
139. 🟢 Toast animations + stacking. **S**
140. 🟢 Micro-delays tuned so nothing feels janky (<100ms perceived). **S**

## 15. Accessibility (141–150)
141. 🔴 Keyboard operable everywhere (nav, graph, dialogs) with visible focus. **M**
142. 🔴 AA color contrast audit (the muted greys are borderline). **S**
143. 🟡 ARIA roles/labels on the graph, tables, toggles. **M**
144. 🟡 Screen-reader pass (reading order, announcements). **M**
145. 🟡 Skip-to-content + landmark regions (partly done). **S**
146. 🟢 Respect OS font-size / zoom without breaking layout. **S**
147. 🟢 Focus trapping in modals; Esc to close. **S**
148. 🟢 Alt text on all meaningful visuals. **S**
149. 🟢 Reduced-transparency / high-contrast mode. **S**
150. 🟢 Automated a11y checks in CI (axe). **M**

## 16. Responsive & mobile (151–160)
151. 🔴 The two-column Traces layout must stack on mobile. **M**
152. 🔴 Mobile nav (hamburger for portal, done on landing — do it in the app too). **S**
153. 🟡 Touch-friendly graph (pinch-zoom, drag-pan) on tablets. **M**
154. 🟡 Dashboard cards reflow to one column. **S**
155. 🟡 Readable trace detail on a phone (transcript-first). **M**
156. 🟢 Bottom-sheet detail panel on mobile. **M**
157. 🟢 Larger tap targets (44px min). **S**
158. 🟢 Landscape-optimized graph view. **S**
159. 🟢 PWA install (offline shell, home-screen icon). **M**
160. 🟢 Test matrix across iOS/Android/desktop breakpoints. **M**

## 17. Performance & scale (161–170)
161. 🔴 Virtualize the trace list and large span trees. **M**
162. 🔴 Debounce filters + cancel in-flight requests. **S**
163. 🟡 Cache trace detail (don't refetch on re-select). **S**
164. 🟡 Code-split heavy views (graph lib lazy-loaded). **S**
165. 🟡 Memoize graph layout; avoid recompute on every render. **S**
166. 🟡 Paginate/stream span detail for huge traces. **M**
167. 🟢 Prefetch on hover for snappy navigation. **S**
168. 🟢 Core Web Vitals budget + monitoring. **M**
169. 🟢 Image/asset optimization (next/image, AVIF). **S**
170. 🟢 Bundle-size budget in CI. **S**

## 18. Project, settings & admin (171–180)
171. 🔴 Project switcher (done) — add create/rename/delete inline + search when many. **S**
172. 🔴 Members & roles UI polish (invite flow, pending states). **M**
173. 🟡 Per-project settings surface: retention, PII masking, ingest rate (backend exists). **M**
174. 🟡 API-key management: last-used, scopes, rotate, usage count. **M**
175. 🟡 Admin console: charts + search + pagination over users/projects. **M**
176. 🟢 Audit log (who did what). **M**
177. 🟢 Usage/quota meter per project. **M**
178. 🟢 Billing/plan surface (even if free — sets up future). **M**
179. 🟢 Danger-zone confirmations with typed project name. **S**
180. 🟢 Org-level grouping of projects. **L**

## 19. Auth & account UX (181–190)
181. 🔴 Password-reset + email-verify flows polished end-to-end (needs SMTP fixed). **M**
182. 🔴 Clear inline validation + error states on login/signup. **S**
183. 🟡 GitHub / Google OAuth sign-in. **M**
184. 🟡 "Remember me" + session-expiry handling with a graceful re-login. **S**
185. 🟡 Profile page (name, avatar, change password). **M**
186. 🟢 2FA / TOTP. **L**
187. 🟢 Magic-link login option. **M**
188. 🟢 Account deletion / data export (GDPR). **M**
189. 🟢 Login rate-limit feedback (friendly, not scary). **S**
190. 🟢 SSO / SAML for teams. **L**

## 20. Alerts, integrations & platform (191–200)
191. 🔴 Alerts UI (backend exists): create/edit threshold rules, see fired history. **M**
192. 🟡 Notification channels UI: email / Slack / webhook config. **M**
193. 🟡 Automation rules (route matching traces → dataset / webhook / online-eval). **L**
194. 🟡 Status/health page for the deployment. **S**
195. 🟡 A TypeScript/JS SDK (huge slice of agents are TS). **L**
196. 🟢 In-app changelog / "what's new" surface. **S**
197. 🟢 Docs search + command palette (⌘K) across the app. **M**
198. 🟢 Public API + API docs for programmatic access. **M**
199. 🟢 Webhooks for trace/alert events. **M**
200. 🟢 MCP debug panel surfaced in-app (the server exists). **M**

---

## Where to actually start — the top 20 (highest value / lowest effort)
Fix the two visible bugs first, then chase the "feels pro" wins that reuse data you already capture:

1. #41 Fix `~$0.0000` cost display · 2. #16 Fix empty minimap · 3. #31 Chat-transcript span view ·
4. #61 Real filters (status/model/time) · 5. #52 Dashboard time-range picker · 6. #51 Real charts ·
7. #12 Node status icons · 8. #2/#3 Row status + cost · 9. #122 Loading skeletons ·
10. #71 Sessions view · 11. #101 Share link expiry/revoke · 12. #37 Exception on failed spans ·
13. #32 Invocation params on LLM spans · 14. #91 Live trace list · 15. #151 Mobile stacking ·
16. #142 Contrast pass · 17. #7 Relative timestamps · 18. #81 Add-to-dataset · 19. #191 Alerts UI ·
20. #171 Inline project CRUD.

Ship those 20 and the product jumps from "functional" to "clearly world-class" — the rest is a
backlog to pull from as real usage tells you what matters.
