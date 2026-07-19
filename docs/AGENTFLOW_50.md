# Agent flow — 50+ points to world-class

Reference: the CereBroZen "Coach Studio" graph — full-bleed canvas, a rich right-hand node
inspector with tabs + CTAs, collapse arrows on both canvas edges, status chips, breadcrumb,
minimap. ProveKit's flow today is a **cramped ~480px box with the detail panel underneath** and
nodes with no actions. This closes that gap.

Tags — Impact: 🔴 structural · 🟡 high-value · 🟢 polish. Effort: S/M/L.

---

## A. Layout & screen usage (the biggest gap) (1–10)
1. 🔴 **Full-bleed canvas.** Make the graph fill the viewport height (not a 480px box) — the
   flow is the hero, give it the screen. **M**
2. 🔴 **Right-hand inspector, not below.** Move the span/node detail into a **resizable right
   panel** (drag the divider), like the reference — canvas left, inspector right. **M**
3. 🔴 **Collapse arrows on both edges.** A `◀`/`▶` toggle on the left (trace list) and right
   (inspector) so either can collapse to give the canvas the whole width. **M**
4. 🔴 **Collapsible left nav** (the app sidebar) with an icon-only rail state. **M**
5. 🟡 Remember panel sizes + collapsed state per user (localStorage). **S**
6. 🟡 Full-screen / "focus" mode for the graph (hide everything else). **S**
7. 🟡 Breadcrumb header (Project ▸ Traces ▸ <trace name>) with quick nav. **S**
8. 🟡 A slim **status bar** of chips above the canvas (env, model, tokens, cost, duration,
   status) — like the reference's `env production` / `drift` chips. **S**
9. 🟢 Responsive: inspector becomes a bottom sheet on narrow screens. **M**
10. 🟢 Keyboard: `[` / `]` collapse panels, `f` fit, `esc` deselect. **S**

## B. Node design & per-node CTAs (2nd biggest gap) (11–22)
11. 🔴 **Every node gets CTAs.** On hover/select, show quick actions: **Copy**, **View I/O**,
    **Add to dataset**, **Share**, **Jump to waterfall**. **M**
12. 🔴 Node header: type badge + name + a **subtitle line** (stage/operation), matching the
    reference's `intake / coach_intake`. **S**
13. 🟡 Status ring/icon per node (✓/✕/⏱) — already have ✓/✕; add a "slow" ⏱ marker. **S**
14. 🟡 Colored **left accent bar** per node type (agent/llm/tool/step) for fast scanning. **S**
15. 🟡 Compact vs expanded node modes — expanded shows tokens/cost/latency inline. **S**
16. 🟡 "Enabled/disabled" and model-tier style meta chips on LLM nodes. **S**
17. 🟢 Node context menu (right-click): copy id, focus subtree, collapse, export. **M**
18. 🟢 Hover tooltip with quick stats (no click needed). **S**
19. 🟢 Selected node gets a stronger ring + the inspector scrolls to it. **S**
20. 🟢 Error nodes pulse subtly / carry the error message on the card. **S**
21. 🟢 Truncate long labels with a tooltip; never overflow the card. **S**
22. 🟢 Node "copy as JSON" and "copy curl to re-fetch" affordances. **S**

## C. Right-hand inspector (tabs + actions) (23–32)
23. 🔴 **Tabbed inspector** like the reference: **Output · Raw · Node · Logs** (and Vars/attrs). **M**
24. 🔴 A clean **metadata table** in the Node tab (node, type, stage, model, tier, tokens, cost,
    temperature, finish_reason, prompt size/hash) — the reference's layout is ideal. **S**
25. 🔴 **Chat-transcript** rendering in the Output tab (roles), raw JSON in the Raw tab. **M**
26. 🟡 Inspector action buttons: **Add to dataset**, **Score 👍/👎**, **Share span**, **Copy**. **S**
27. 🟡 "Logs" tab: the span's events with level filter. **S**
28. 🟡 Retriever spans: a "Retrieved" tab with docs + relevance scores. **M**
29. 🟡 Tool spans: args + result rendered distinctly, with a "re-run tool" stub. **M**
30. 🟢 Sticky inspector header (name + status) while the body scrolls. **S**
31. 🟢 Prev/next span arrows in the inspector to walk the trace. **S**
32. 🟢 Deep-link to a span (`?span=`) so the inspector opens on load. **S**

## D. Canvas controls & navigation (33–40)
33. 🔴 **Auto-layout with dagre** (left→right) so wide/deep traces don't overlap. **M**
34. 🟡 Richer control cluster (like the reference's left toolbar): zoom in/out, **fit**,
    **center**, **auto-layout**, **toggle grid**, **toggle minimap**. **S**
35. 🟡 A **real minimap** that's useful (color by type, viewport rect) — hide on tiny graphs
    (done) but make it great on big ones. **S**
36. 🟡 Search-in-graph: type to highlight/zoom to matching nodes. **M**
37. 🟢 Fit-to-selection + "reset view". **S**
38. 🟢 Pan with space-drag; zoom to cursor. **S**
39. 🟢 Breadcrumb of the current focus subtree when zoomed in. **S**
40. 🟢 Export the graph as PNG/SVG. **S**

## E. Collapse / expand / grouping (41–46)
41. 🔴 **Collapse a subtree** into a single node with a child count (huge for big traces). **M**
42. 🟡 Aggregate repeated sibling steps (e.g. 10 `doc:` nodes → one "×10" node, expandable). **M**
43. 🟡 Collapse-all / expand-all controls. **S**
44. 🟡 Toggle: hide `step` nodes to declutter to just agent/llm/tool. **S**
45. 🟢 Group by sub-agent with a labelled container/frame around each cluster. **M**
46. 🟢 Critical-path highlight (longest chain) as a one-click view. **M**

## F. Interaction, real-time & polish (47–56)
47. 🟡 Animate nodes/edges appearing as a **live trace streams in**. **M**
48. 🟡 Smooth camera transitions when selecting/collapsing (no hard jumps). **S**
49. 🟡 Edge styling by relation + animated flow on the active path (partly done). **S**
50. 🟡 Cost/latency **heat coloring** toggle across nodes. **S**
51. 🟢 Empty/loading skeleton for the canvas (not a blank box). **S**
52. 🟢 Light theme parity for the graph. **M**
53. 🟢 Keyboard nav between nodes (arrows follow edges). **M**
54. 🟢 A11y: nodes as a navigable list for screen readers; focus rings. **M**
55. 🟢 Virtualize / cull off-screen nodes for 1000+ span traces. **M**
56. 🟢 "Compare two traces" side-by-side in the same canvas. **L**

---

## The 8 that transform it (do these first)
The reference's magic is **layout + inspector + CTAs**, not a hundred small things:

1. **#1 Full-bleed canvas** (fill the viewport).
2. **#2 Right-hand resizable inspector** (move detail from below → beside).
3. **#3 Collapse arrows** on both canvas edges.
4. **#23 Tabbed inspector** (Output / Raw / Node / Logs).
5. **#11 Per-node CTAs** (Add to dataset / Score / Share / Copy on hover).
6. **#33 Dagre auto-layout** (no overlap on real traces).
7. **#41 Collapse subtree** (tame big traces).
8. **#8 Status-chip bar** above the canvas.

Ship those and the flow view jumps from "a chart in a box" to the CereBroZen-class studio in
the reference. Everything else is refinement on top.
