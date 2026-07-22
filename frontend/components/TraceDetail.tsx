"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { api, API_BASE, Feedback, getProjectId, TraceSpan } from "@/lib/api";
import { estimateCost, fmtCost } from "@/lib/cost";
import { useVirtualRows } from "@/lib/useVirtualRows";
import TraceGraph, { heatColor } from "@/components/TraceGraph";
import Playground from "@/components/Playground";
import { SpanBody } from "@/components/spanRenderers";

const TYPE_COLOR: Record<string, string> = {
  agent: "var(--accent)", llm: "var(--blue)", tool: "var(--purple)", step: "var(--muted)",
};
const LOG_COLOR: Record<string, string> = {
  ERROR: "var(--red)", CRITICAL: "var(--red)", WARNING: "var(--amber)", INFO: "var(--blue)", DEBUG: "var(--muted)",
};
const ROLE_COLOR: Record<string, string> = {
  system: "var(--purple)", user: "var(--blue)", assistant: "var(--green)", tool: "var(--amber)",
};

// Detect and normalize an LLM message list so we can render it as a chat transcript instead of
// a raw JSON blob. Handles a bare array, a {"messages": [...]} wrapper (OpenInference's
// input.value / current gen_ai.input.messages shape), and — for completions-style payloads like
// legacy {"prompt": "..."} calls — falls back to a single user message so content isn't lost.
// Returns null only when the value truly isn't message-shaped (plain non-JSON text).
export function parseMessages(v: any): { role: string; content: string }[] | null {
  let data = v;
  if (typeof v === "string") {
    const t = v.trim();
    if (!t.startsWith("[") && !t.startsWith("{")) return null;
    try { data = JSON.parse(t); } catch { return null; }
  }
  if (!data) return null;
  let arr = Array.isArray(data) ? data : Array.isArray(data?.messages) ? data.messages : null;
  if (!arr) {
    // data is a non-array object here (an array would have satisfied the ternary above).
    const fallback = typeof data?.prompt === "string" ? data.prompt
      : typeof data?.input === "string" ? data.input
      : typeof data?.text === "string" ? data.text : null;
    if (fallback == null) return null;
    arr = [{ role: "user", content: fallback }];
  }
  const msgs = arr.map((m: any) => {
    if (m == null || typeof m !== "object") return null;
    const role = m.role || m.type || m.name;
    if (!role) return null;
    let content = m.content ?? m.text ?? m.message ?? "";
    if (Array.isArray(content)) {
      // Flatten multimodal content blocks to their text parts only — a non-text block (image,
      // audio, …) can't be edited as text, and dumping its raw JSON would get sent back to the
      // model verbatim if re-run, so it's replaced with a short placeholder instead.
      content = content.map((c: any) => (typeof c === "string" ? c : c?.text || (c?.type ? `[${c.type}]` : ""))).filter(Boolean).join(" ");
    } else if (typeof content !== "string") {
      content = JSON.stringify(content, null, 2);
    }
    return { role: String(role), content };
  }).filter(Boolean) as { role: string; content: string }[];
  return msgs.length ? msgs : null;
}

function Transcript({ msgs }: { msgs: { role: string; content: string }[] }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6, marginBottom: 8 }}>
      {msgs.map((m, i) => (
        <div key={i} style={{ border: "1px solid var(--border)", borderRadius: 8, overflow: "hidden" }}>
          <div style={{ fontSize: 10, fontWeight: 700, textTransform: "uppercase", letterSpacing: 0.4,
            padding: "3px 8px", color: ROLE_COLOR[m.role] || "var(--muted)", background: "var(--bg-2)" }}>
            {m.role}
          </div>
          <pre style={{ ...pre, border: "none", borderRadius: 0, maxHeight: 200 }}>{m.content || <span className="muted">—</span>}</pre>
        </div>
      ))}
    </div>
  );
}

// The default span body: input, output, and the error if it failed. Every custom span renderer
// falls back to exactly this, so it lives in one place and both the inspector and the waterfall
// row use it.
function DefaultBody({ span: s }: { span: TraceSpan }) {
  return (
    <>
      <IO label="Input" value={s.request?.input} />
      <IO label="Output" value={s.result?.text} />
      {(s.error || s.status === "failed") && <ErrorBlock error={s.error} />}
    </>
  );
}

// Renders either a chat transcript (if the value is message-shaped) or a plain pre block.
function IO({ label, value }: { label: string; value: any }) {
  const msgs = parseMessages(value);
  if (msgs) {
    return (
      <div style={{ marginBottom: 8 }}>
        <div className="muted" style={fieldLabel}>{label}</div>
        <Transcript msgs={msgs} />
      </div>
    );
  }
  return <Field label={label}>{textOf(value)}</Field>;
}

export default function TraceDetail({ spans, traceId, readOnly = false }: { spans: TraceSpan[]; traceId?: string; readOnly?: boolean }) {
  const [view, setView] = useState<"flow" | "waterfall">("flow");
  const ids = new Set(spans.map((s) => s.span_id));
  const root = spans.find((s) => !s.parent_span_id || !ids.has(s.parent_span_id));
  const [picked, setPicked] = useState<string | null>(root?.span_id ?? null);
  const [inspectorOpen, setInspectorOpen] = useState(true);
  const [pgSpan, setPgSpan] = useState<TraceSpan | null>(null);
  const [tip, setTip] = useState(false);
  // Deep link: `#span-<id>` points at one span. Read on mount *and* on hashchange so a pasted
  // link works without a reload, and re-read per trace so the target is resolved against the
  // spans actually loaded.
  const [hashSpan, setHashSpan] = useState<string | null>(null);
  useEffect(() => {
    const read = () => {
      const m = /^#span-(.+)$/.exec(window.location.hash || "");
      setHashSpan(m ? decodeURIComponent(m[1]) : null);
    };
    read();
    window.addEventListener("hashchange", read);
    return () => window.removeEventListener("hashchange", read);
  }, []);
  useEffect(() => {
    if (hashSpan && spans.some((s) => s.span_id === hashSpan)) setPicked(hashSpan);
  }, [hashSpan, spans]);
  useEffect(() => { try { setTip(!localStorage.getItem("pk_debug_tip")); } catch { /* no storage */ } }, []);
  const dismissTip = () => { setTip(false); try { localStorage.setItem("pk_debug_tip", "1"); } catch { /* no storage */ } };
  const totalTok = spans.reduce((n, s) => n + (s.result?.meta?.usage?.input_tokens || 0) + (s.result?.meta?.usage?.output_tokens || 0), 0);
  const totalCost = fmtCost(spans.reduce((n, s) => n + (estimateCost(s.request?.model, s.result?.meta?.usage?.input_tokens, s.result?.meta?.usage?.output_tokens) || 0), 0) || null);
  const sel = spans.find((s) => s.span_id === picked) || root;
  // A replayed branch containing diverged spans is a hypothesis, not a reproduction: something
  // upstream changed the inputs to a step ProveKit can't re-run, so its recorded output — and
  // everything derived from it — is no longer what this run would have produced. Said once at
  // the top, because the per-node badges are easy to read past.
  const divergedCount = spans.filter((s) => (s.result?.meta as any)?.replay_state === "diverged").length;
  // Said once at the top of a shared trace: a reader who doesn't know fields were withheld will
  // read an empty prompt as a bug in the agent rather than a deliberate redaction.
  const withheld = Array.from(new Set(spans.flatMap(withheldOf))).sort();

  return (
    <div>
      {withheld.length > 0 && (
        <div style={{ display: "flex", gap: 8, alignItems: "flex-start", fontSize: 12.5,
                      border: "1px solid var(--border-strong)", borderRadius: 10, padding: "9px 11px",
                      marginBottom: 10 }}>
          <span aria-hidden>🔒</span>
          <span>
            <strong>Partly redacted.</strong>{" "}
            <span className="muted">
              This link withholds {withheld.join(", ")}. Those fields were removed before the
              trace was sent — nothing here was hidden client-side.
            </span>
          </span>
        </div>
      )}
      {divergedCount > 0 && (
        <div style={{ display: "flex", gap: 8, alignItems: "flex-start", fontSize: 12.5,
                      border: "1px solid var(--amber)", borderRadius: 10, padding: "9px 11px",
                      marginBottom: 10, color: "var(--amber)" }}>
          <span aria-hidden>⚠</span>
          <span>
            <strong>{divergedCount} span{divergedCount === 1 ? "" : "s"} diverged.</strong>{" "}
            <span className="muted">
              Their inputs changed, so their recorded outputs — and anything downstream — aren&apos;t
              what this run would actually have produced. ProveKit can&apos;t re-run your tools;
              use webhook replay for an exact re-run.
            </span>
          </span>
        </div>
      )}
      {/* Header: name + status-chip bar + view toggle */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10, marginBottom: 10, paddingBottom: 8, borderBottom: "1px solid var(--border)", flexWrap: "wrap" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0, flexWrap: "wrap" }}>
          <span style={{ fontSize: 14, fontWeight: 600 }}>{root?.label || "trace"}</span>
          <span style={chip()}>{spans.length} spans</span>
          <span style={chip()}>{root?.duration_ms ?? 0}ms</span>
          {totalTok ? <span style={chip()}>{totalTok.toLocaleString()} tok</span> : null}
          {totalCost ? <span style={chip()}>{totalCost}</span> : null}
          <span style={chip(root?.status === "failed" ? "var(--red)" : "var(--green)")}>{root?.status ?? "—"}</span>
          {root?.session_id && <span style={chip("var(--purple)")} title="session / thread">◆ {root.session_id}</span>}
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexShrink: 0 }}>
          {!readOnly && traceId && <ShareButton traceId={traceId} />}
          {/* data-tour marks the elements the product tour rings (components/Tour.tsx). */}
          <div data-tour="view-toggle" style={{ display: "flex", gap: 3, background: "var(--bg-2)", borderRadius: 8, padding: 2 }}>
            {(["flow", "waterfall"] as const).map((v) => (
              <button key={v} onClick={() => setView(v)} style={toggleBtn(view === v)}>
                {v === "flow" ? "Flow" : "Waterfall"}
              </button>
            ))}
          </div>
        </div>
      </div>

      {tip && !readOnly && (
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10, padding: "8px 12px",
          borderRadius: 8, fontSize: 12.5, background: "var(--accent-soft)", border: "1px solid var(--accent)" }}>
          <span>✨</span>
          <span style={{ flex: 1 }}><b>New — debug with real data:</b> click an <b>LLM</b> node, then <b>▶ Edit &amp; re-run</b> to edit its prompt/variables and re-run it, or <b>⑂ Replay flow</b> to fork the whole trace.</span>
          <button onClick={dismissTip} className="btn btn-sm btn-ghost" style={{ flexShrink: 0 }}>Got it</button>
        </div>
      )}

      {view === "flow" ? (
        // Full-height studio: canvas fills the space, a resizable/collapsible inspector on the right.
        <div className="flow-studio" style={{ display: "flex", height: "62vh", minHeight: 420, border: "1px solid var(--border)", borderRadius: 10, overflow: "hidden", position: "relative" }}>
          <div className="flow-canvas" data-tour="flow-canvas" style={{ flex: 1, minWidth: 0, position: "relative" }}>
            <TraceGraph spans={spans} selected={picked} onSelect={setPicked} fill />
          </div>
          {/* collapse toggle on the divider */}
          <button className="flow-collapse-btn" onClick={() => setInspectorOpen((o) => !o)} title={inspectorOpen ? "Hide inspector" : "Show inspector"}
            style={{ ...collapseBtn, right: inspectorOpen ? 388 : 8 }}>{inspectorOpen ? "›" : "‹"}</button>
          {inspectorOpen && (
            <div className="flow-inspector" data-tour="inspector" style={{ width: 380, flexShrink: 0, borderLeft: "1px solid var(--border)", overflowY: "auto", background: "var(--panel)" }}>
              {sel ? <Inspector span={sel} traceId={traceId} readOnly={readOnly} onPlayground={setPgSpan} /> : <div className="muted" style={{ padding: 16, fontSize: 13 }}>Click a node to inspect it.</div>}
            </div>
          )}
          {pgSpan && <Playground span={pgSpan} traceId={traceId} onClose={() => setPgSpan(null)} />}
        </div>
      ) : (
        <Tree spans={spans} focusSpan={hashSpan} />
      )}

      {!readOnly && traceId && <FeedbackPanel traceId={traceId} />}
    </div>
  );
}

// Right-hand node inspector — tabbed (Output / Raw / Node / Logs) with per-node CTAs.
function Inspector({ span: s, traceId, readOnly, onPlayground }: { span: TraceSpan; traceId?: string; readOnly?: boolean; onPlayground?: (s: TraceSpan) => void }) {
  const [tab, setTab] = useState<"output" | "raw" | "node" | "logs" | "notes">("output");
  const meta = s.result?.meta || {};
  const params = meta.params || {};
  const events: any[] = Array.isArray(meta.events) ? meta.events : [];
  const cost = fmtCost(estimateCost(s.request?.model, s.result?.meta?.usage?.input_tokens, s.result?.meta?.usage?.output_tokens));
  const copy = (v: any) => navigator.clipboard?.writeText(typeof v === "string" ? v : JSON.stringify(v, null, 2));

  const rows: [string, React.ReactNode][] = [
    ["type", s.type],
    ["status", <span style={{ color: s.status === "failed" ? "var(--red)" : "var(--green)" }}>{s.status}</span>],
    ["duration", `${s.duration_ms} ms`],
  ];
  if (s.request?.provider) rows.push(["provider", s.request.provider]);
  if (s.request?.model) rows.push(["model", s.request.model]);
  if (s.request?.operation) rows.push(["operation", s.request.operation]);
  if (params.temperature != null) rows.push(["temperature", String(params.temperature)]);
  if (params.top_p != null) rows.push(["top_p", String(params.top_p)]);
  if (params.max_tokens != null) rows.push(["max_tokens", String(params.max_tokens)]);
  if (meta.finish_reason != null) rows.push(["finish_reason", String(meta.finish_reason)]);
  if (tokens(s)) rows.push(["tokens", tokens(s)]);
  if (cost) rows.push(["est. cost", cost]);
  if (s.span_id) rows.push(["span id", <span className="mono" style={{ fontSize: 11 }}>{s.span_id}</span>]);
  if (s.session_id) rows.push(["session", s.session_id]);

  const tabs: [typeof tab, string, number?][] = [
    ["output", "Output"], ["raw", "Raw"], ["node", "Node"], ["logs", "Logs", events.length],
  ];
  if (!readOnly && traceId) tabs.push(["notes", "Notes"]);

  return (
    <div>
      <div style={{ position: "sticky", top: 0, background: "var(--panel)", padding: "12px 14px 0", zIndex: 1 }}>
        <div style={{ fontSize: 13, fontWeight: 600, display: "flex", alignItems: "center", gap: 7 }}>
          <span style={insBadge(s.type, s.status)}>{s.type}</span>
          <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{s.label}</span>
          {withheldOf(s).length > 0 && (
            <span style={{ ...chip(), flexShrink: 0 }} title={`Withheld from this share link: ${withheldOf(s).join(", ")}`}>
              🔒 {withheldOf(s).join(", ")}
            </span>
          )}
        </div>
        <div style={{ display: "flex", gap: 2, marginTop: 10, borderBottom: "1px solid var(--border)" }}>
          {tabs.map(([t, label, n]) => (
            <button key={t} onClick={() => setTab(t)} style={insTab(tab === t)}>
              {label}{n ? <span style={{ marginLeft: 4, fontSize: 9.5, color: "var(--muted)" }}>{n}</span> : null}
            </button>
          ))}
        </div>
      </div>

      <div style={{ padding: 14 }}>
        {/* A team can render its own domain span here (components/spanRenderers.tsx); anything
            unclaimed — or a renderer that declines or throws — lands on DefaultBody. */}
        {tab === "output" && <SpanBody span={s} fallback={<DefaultBody span={s} />} />}
        {tab === "raw" && (
          <pre style={{ ...pre, maxHeight: "48vh" }}>{JSON.stringify({ request: s.request, result: s.result }, null, 2)}</pre>
        )}
        {tab === "node" && (
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12.5 }}>
            <tbody>
              {rows.map(([k, v], i) => (
                <tr key={i} style={{ borderTop: i ? "1px solid var(--border)" : "none" }}>
                  <td style={{ padding: "7px 0", color: "var(--muted)", width: "42%" }}>{k}</td>
                  <td style={{ padding: "7px 0", textAlign: "right", fontFamily: "var(--font-mono)" }}>{v}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {tab === "logs" && (
          events.length ? (
            <div style={{ ...pre, padding: 8 }}>
              {events.map((e, i) => (
                <div key={i} style={{ display: "flex", gap: 8 }}>
                  <span style={{ color: LOG_COLOR[e.level] || "var(--muted)", fontWeight: 600, minWidth: 44 }}>{e.level}</span>
                  <span>{e.name}</span>
                </div>
              ))}
            </div>
          ) : <div className="muted" style={{ fontSize: 12.5 }}>No logs on this span.</div>
        )}

        {tab === "notes" && traceId && <SpanNotes traceId={traceId} spanId={s.span_id} />}

        {/* per-node CTAs */}
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 14, paddingTop: 12, borderTop: "1px solid var(--border)" }}>
          {!readOnly && s.type === "llm" && onPlayground && (
            <button className="btn btn-sm" style={{ borderColor: "var(--accent)", color: "var(--accent)" }}
              onClick={() => onPlayground(s)} title="Edit this call's prompt and re-run it with real data">▶ Edit &amp; re-run</button>
          )}
          <button className="btn btn-sm" onClick={() => copy(s.result?.text ?? s.request?.input ?? "")}>Copy I/O</button>
          <button className="btn btn-sm" onClick={() => copy({ request: s.request, result: s.result })}>Copy JSON</button>
          {!readOnly && traceId && <ScoreButtons traceId={traceId} />}
        </div>
      </div>
    </div>
  );
}

// Per-span collaboration notes, shown in the inspector's Notes tab.
function SpanNotes({ traceId, spanId }: { traceId: string; spanId: string }) {
  const [notes, setNotes] = useState<import("@/lib/api").SpanNote[] | null>(null);
  const [body, setBody] = useState("");
  const [busy, setBusy] = useState(false);
  const load = () => api.notes(traceId).then(setNotes).catch(() => setNotes([]));
  useEffect(() => { load(); }, [traceId]);
  const mine = (notes || []).filter((n) => n.span_id === spanId);
  const add = async () => {
    if (!body.trim()) return;
    setBusy(true);
    try { await api.addNote(traceId, { span_id: spanId, body: body.trim() }); setBody(""); load(); }
    finally { setBusy(false); }
  };
  const fmt = (s: string) => { try { return new Date(s).toLocaleString(); } catch { return ""; } };
  return (
    <div>
      <div style={{ display: "flex", flexDirection: "column", gap: 8, marginBottom: 10 }}>
        {notes == null ? <span className="muted" style={{ fontSize: 12.5 }}>Loading…</span>
          : mine.length === 0 ? <span className="muted" style={{ fontSize: 12.5 }}>No notes on this span yet.</span>
          : mine.map((n) => (
            <div key={n.id} style={{ border: "1px solid var(--border)", borderRadius: 8, padding: "8px 10px" }}>
              <div style={{ fontSize: 12.5, whiteSpace: "pre-wrap" }}>{n.body}</div>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 5 }}>
                <span className="muted" style={{ fontSize: 10.5 }}>{n.author || "—"} · {fmt(n.created_at)}</span>
                <button className="btn btn-sm btn-ghost" onClick={async () => { await api.deleteNote(n.id); load(); }}>Delete</button>
              </div>
            </div>
          ))}
      </div>
      <textarea value={body} onChange={(e) => setBody(e.target.value)} placeholder="Add a note for your team…"
        onKeyDown={(e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) add(); }}
        style={{ width: "100%", minHeight: 56, resize: "vertical", background: "var(--panel-2)", color: "var(--text)",
          border: "1px solid var(--border-strong)", borderRadius: 8, padding: "8px 10px", fontSize: 12.5 }} />
      <button className="btn btn-sm" onClick={add} disabled={busy || !body.trim()} style={{ marginTop: 6 }}>Add note</button>
    </div>
  );
}

function ScoreButtons({ traceId }: { traceId: string }) {
  const [done, setDone] = useState("");
  const send = async (value: string) => {
    try { await api.addFeedback(traceId, { name: "thumbs", value }); setDone(value === "up" ? "👍" : "👎"); setTimeout(() => setDone(""), 1500); } catch { /* ignore */ }
  };
  return (
    <>
      <button className="btn btn-sm" onClick={() => send("up")}>👍</button>
      <button className="btn btn-sm" onClick={() => send("down")}>👎</button>
      {done && <span style={{ fontSize: 12, alignSelf: "center" }}>{done} saved</span>}
    </>
  );
}

// Fields a share link can withhold, in the order they matter to whoever is deciding. The names
// must match services/share.py's MASKABLE_FIELDS — the server rejects anything else rather than
// quietly sharing a field it didn't recognise.
const WITHHOLDABLE: [string, string, string][] = [
  ["input", "Prompts", "everything sent to the model"],
  ["output", "Completions", "everything the model answered"],
  ["logs", "Log events", "log lines your code attached to a span"],
  ["error", "Error messages", "exception text, which often quotes data"],
  ["label", "Span names", "often a customer id or a routing decision"],
];

// Posted directly rather than through lib/api's `api` object: both routes exist only for this
// panel, and the request body is exactly the checkbox state below.
async function postShare<T>(path: string, body: unknown): Promise<T> {
  const pid = getProjectId();
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST", credentials: "include", body: JSON.stringify(body),
    headers: { "Content-Type": "application/json", ...(pid ? { "X-Project-Id": pid } : {}) },
  });
  if (!res.ok) throw new Error(String(res.status));
  return res.json();
}

const ISSUE_REPO_KEY = "pk_issue_repo";

// Share + hand off. The withheld fields are stripped by the server before the shared response
// is built (services/share.py), so unchecking a box here is a real redaction and not a UI that
// hides what it still downloaded.
function ShareButton({ traceId }: { traceId: string }) {
  const [open, setOpen] = useState(false);
  const [withhold, setWithhold] = useState<string[]>([]);
  const [label, setLabel] = useState("Share");
  const [repo, setRepo] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => { try { setRepo(localStorage.getItem(ISSUE_REPO_KEY) || ""); } catch { /* no storage */ } }, []);
  const toggle = (f: string) =>
    setWithhold((w) => (w.includes(f) ? w.filter((x) => x !== f) : [...w, f]));
  const flash = (msg: string) => { setLabel(msg); setTimeout(() => setLabel("Share"), 2200); };

  const copyLink = async () => {
    setBusy(true);
    try {
      // Same-origin link, not the server's configured web_base_url: whoever is looking at this
      // trace is already on the host their teammates use.
      const r = await postShare<{ token: string }>(`/api/traces/${encodeURIComponent(traceId)}/share/redacted`, { withhold });
      await navigator.clipboard?.writeText(`${window.location.origin}/shared/${r.token}`);
      setOpen(false);
      flash(withhold.length ? `Copied · ${withhold.length} field${withhold.length === 1 ? "" : "s"} withheld` : "Copied · link");
    } catch { flash("Failed"); } finally { setBusy(false); }
  };

  const openIssue = async () => {
    setBusy(true);
    try { localStorage.setItem(ISSUE_REPO_KEY, repo.trim()); } catch { /* no storage */ }
    try {
      const r = await postShare<{ issue_url: string }>(`/api/traces/${encodeURIComponent(traceId)}/issue-link`, { withhold, repo: repo.trim() });
      // A new tab, prefilled and authored by the person who clicked it — ProveKit holds no
      // tracker credential and files nothing on anyone's behalf.
      window.open(r.issue_url, "_blank", "noopener,noreferrer");
      setOpen(false);
    } catch { flash("Check the repo"); } finally { setBusy(false); }
  };

  return (
    <div style={{ position: "relative" }}>
      <button className="btn btn-sm" onClick={() => setOpen((o) => !o)} aria-expanded={open}>{label} ▾</button>
      {open && (
        <div style={sharePanel}>
          <div className="muted" style={fieldLabel}>Withhold from the link</div>
          {WITHHOLDABLE.map(([f, name, why]) => (
            <label key={f} title={why} style={{ display: "flex", gap: 8, alignItems: "baseline", fontSize: 12.5, padding: "3px 0", cursor: "pointer" }}>
              <input type="checkbox" checked={withhold.includes(f)} onChange={() => toggle(f)} />
              <span>{name}<span className="muted" style={{ fontSize: 11 }}> · {why}</span></span>
            </label>
          ))}
          <div className="muted" style={{ fontSize: 11, lineHeight: 1.45, margin: "6px 0 10px" }}>
            Withheld fields are removed on the server — they never reach the shared page.
          </div>
          <button className="btn btn-sm" disabled={busy} onClick={copyLink} style={{ width: "100%" }}>Copy share link</button>
          <div style={{ borderTop: "1px solid var(--border)", margin: "12px 0 10px" }} />
          <div className="muted" style={fieldLabel}>File an issue</div>
          <input value={repo} onChange={(e) => setRepo(e.target.value)} placeholder="owner/repo or project URL"
            style={{ width: "100%", background: "var(--panel-2)", color: "var(--text)", fontSize: 12,
              border: "1px solid var(--border-strong)", borderRadius: 8, padding: "6px 9px", marginBottom: 7 }} />
          <button className="btn btn-sm" disabled={busy || !repo.trim()} onClick={openIssue} style={{ width: "100%" }}>
            Open prefilled issue ↗
          </button>
        </div>
      )}
    </div>
  );
}

function FeedbackPanel({ traceId }: { traceId: string }) {
  const [items, setItems] = useState<Feedback[]>([]);
  const [comment, setComment] = useState("");
  const load = () => api.feedback(traceId).then(setItems).catch(() => {});
  useEffect(() => { load(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [traceId]);
  const add = async (body: { name: string; value?: string; score?: number | null; comment?: string }) => {
    try { await api.addFeedback(traceId, body); setComment(""); load(); } catch { /* ignore */ }
  };
  return (
    <div style={{ marginTop: 14, paddingTop: 12, borderTop: "1px solid var(--border)" }}>
      <div className="muted" style={fieldLabel}>Feedback</div>
      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap", marginBottom: items.length ? 10 : 0 }}>
        <button className="btn btn-sm" onClick={() => add({ name: "thumbs", value: "up", comment })}>👍 Good</button>
        <button className="btn btn-sm" onClick={() => add({ name: "thumbs", value: "down", comment })}>👎 Bad</button>
        <input value={comment} onChange={(e) => setComment(e.target.value)} placeholder="optional comment…"
          style={{ flex: 1, minWidth: 140, background: "var(--panel-2)", color: "var(--text)",
            border: "1px solid var(--border-strong)", borderRadius: 8, padding: "6px 10px", fontSize: 12.5 }} />
      </div>
      {items.map((f) => (
        <div key={f.id} style={{ display: "flex", gap: 8, alignItems: "baseline", fontSize: 12.5, padding: "3px 0" }}>
          <span style={{ fontWeight: 600 }}>{f.name}</span>
          {f.value && <span>{f.value === "up" ? "👍" : f.value === "down" ? "👎" : f.value}</span>}
          {f.score != null && <span className="mono">{f.score}</span>}
          {f.comment && <span className="muted">“{f.comment}”</span>}
          <span className="muted" style={{ marginLeft: "auto", fontSize: 11 }}>{f.source}</span>
        </div>
      ))}
    </div>
  );
}

function toggleBtn(active: boolean): React.CSSProperties {
  return {
    fontSize: 12, padding: "4px 13px", borderRadius: 6, cursor: "pointer", border: "none",
    background: active ? "var(--panel)" : "transparent",
    color: active ? "var(--text)" : "var(--muted)", fontWeight: active ? 600 : 400,
  };
}

// Compact duration label: "840ms", "1.2s", "12s".
function fmtDur(ms: number): string {
  if (ms >= 1000) return `${(ms / 1000).toFixed(ms >= 10000 ? 0 : 1)}s`;
  return `${Math.round(ms)}ms`;
}

// Waterfall row height before it's measured. Only the estimate for off-screen rows depends on
// this, so being a pixel or two out costs nothing but scrollbar precision while scrolling fast.
const ROW_H = 30;
// Below this many rows the list renders exactly as it always has: no scroll container, no
// spacers, every row in the page flow. Windowing a 40-span trace would only add a scrollbar.
const VIRTUALIZE_FROM = 120;

const rowDomId = (spanId: string) => `pk-span-${spanId}`;

function Tree({ spans, focusSpan }: { spans: TraceSpan[]; focusSpan?: string | null }) {
  const [open, setOpen] = useState<string | null>(spans[0]?.span_id ?? null);
  const [heat, setHeat] = useState(false);
  // Roving-tabindex cursor. Virtualization unmounts off-screen rows, so Tab alone can no longer
  // reach every span — the arrow keys drive the list and only the cursor row is tabbable.
  const [cursor, setCursor] = useState(0);
  const maxDur = Math.max(1, ...spans.map((s) => s.duration_ms || 0));

  // Tree shape + timing, flattened to a row list. Memoised because the virtualizer re-renders on
  // every scroll frame and none of this depends on scroll position.
  const { rows, offsetMs, totalMs, hasReal } = useMemo(() => {
    const kids: Record<string, TraceSpan[]> = {};
    const ids = new Set(spans.map((s) => s.span_id));
    for (const s of spans) {
      const p = s.parent_span_id && ids.has(s.parent_span_id) ? s.parent_span_id : "__root__";
      (kids[p] ||= []).push(s);
    }
    const startNs = (s: TraceSpan): bigint | null => {
      const v = s.result?.meta?.start_ns;
      return v ? BigInt(v) : null;
    };
    const starts = spans.map(startNs).filter((x): x is bigint => x !== null);
    const hasReal = starts.length > 0;
    const t0 = starts.length ? starts.reduce((a, b) => (b < a ? b : a)) : 0n;

    // Synthetic fallback timing: when spans carry no wall-clock timestamps we still want a
    // readable waterfall, so lay siblings out sequentially (each starts when the previous ends)
    // nested under their parent's start. It's an approximation — flagged in the UI below —
    // because without timestamps we can't know which siblings actually ran in parallel.
    const synth: Record<string, number> = {};
    {
      let cursor = 0;
      const layout = (s: TraceSpan, start: number) => {
        synth[s.span_id] = start;
        let c = start;
        for (const ch of kids[s.span_id] || []) { layout(ch, c); c += ch.duration_ms || 0; }
      };
      for (const r of kids["__root__"] || []) { layout(r, cursor); cursor += r.duration_ms || 0; }
    }

    // A span's start offset (ms from trace start): real timestamp if present, else synthetic.
    const offsetMs = (s: TraceSpan): number => {
      const st = startNs(s);
      if (st !== null) return Number(st - t0) / 1e6;
      return synth[s.span_id] ?? 0;
    };
    const totalMs = Math.max(1, ...spans.map((s) => offsetMs(s) + (s.duration_ms || 0)));

    // Depth-first flatten, in exactly the order the recursive renderer used to emit: a span, then
    // its whole subtree. Indentation was always a paddingLeft, never real nesting, so the flat
    // list is pixel-identical — and a row's index is now all the virtualizer needs to place it.
    const rows: { span: TraceSpan; depth: number }[] = [];
    const walk = (parent: string, depth: number) => {
      for (const s of kids[parent] || []) { rows.push({ span: s, depth }); walk(s.span_id, depth + 1); }
    };
    walk("__root__", 0);

    return { rows, offsetMs, totalMs, hasReal };
  }, [spans]);

  const virtual = rows.length >= VIRTUALIZE_FROM;
  const v = useVirtualRows(rows.length, { estimate: ROW_H, overscan: 8, enabled: virtual });
  const { scrollToIndex, scrollRef } = v;

  // The virtualized list scrolls, so it may carry a scrollbar that the (non-scrolling) time
  // ruler above it doesn't. Reserve the same width on the ruler or its ticks drift off the bars.
  const [gutter, setGutter] = useState(0);
  useEffect(() => {
    const el = scrollRef.current;
    if (!virtual || !el || typeof ResizeObserver === "undefined") { setGutter(0); return; }
    const m = () => setGutter(el.offsetWidth - el.clientWidth);
    m();
    const ro = new ResizeObserver(m);
    ro.observe(el);
    return () => ro.disconnect();
  }, [virtual, scrollRef]);

  const indexOf = useMemo(() => {
    const m = new Map<string, number>();
    rows.forEach((r, i) => m.set(r.span.span_id, i));
    return m;
  }, [rows]);

  // Bring a row into view whether or not it's mounted: scrollToIndex puts it inside the window
  // (so React mounts it), and the node itself then does the fine alignment — which also scrolls
  // the *page* when the list isn't virtualized and so has no scroll container of its own.
  const reveal = useCallback((index: number, focus = false) => {
    const id = rows[index]?.span.span_id;
    if (!id) return;
    scrollToIndex(index, "center");
    requestAnimationFrame(() => {
      const el = document.getElementById(rowDomId(id));
      el?.scrollIntoView({ block: "nearest" });
      if (focus) el?.focus({ preventScroll: true });
    });
  }, [rows, scrollToIndex]);

  // Deep link — open and scroll to the linked span even if it sits 800 rows down.
  useEffect(() => {
    if (!focusSpan) return;
    const i = indexOf.get(focusSpan);
    if (i == null) return;
    setOpen(focusSpan);
    setCursor(i);
    reveal(i);
  }, [focusSpan, indexOf, reveal]);

  const select = (index: number) => {
    const id = rows[index]?.span.span_id;
    if (!id) return;
    setCursor(index);
    setOpen((cur) => (cur === id ? null : id));
    // Keep the URL on the span under inspection so "look at this one" is a paste-able link.
    // replaceState, not push — expanding rows shouldn't fill up the back button.
    try { window.history.replaceState(null, "", `#span-${encodeURIComponent(id)}`); } catch { /* no history */ }
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    const move = (to: number) => {
      e.preventDefault();
      const i = Math.max(0, Math.min(to, rows.length - 1));
      setCursor(i);
      reveal(i, true);
    };
    const at = rows[cursor]?.span.span_id;
    switch (e.key) {
      case "ArrowDown": return move(cursor + 1);
      case "ArrowUp": return move(cursor - 1);
      case "PageDown": return move(cursor + 10);
      case "PageUp": return move(cursor - 10);
      case "Home": return move(0);
      case "End": return move(rows.length - 1);
      case "ArrowRight": e.preventDefault(); if (at) setOpen(at); return;
      case "ArrowLeft": e.preventDefault(); setOpen(null); return;
    }
  };

  const bar = (s: TraceSpan) => {
    const left = (offsetMs(s) / totalMs) * 100;
    const width = Math.max(((s.duration_ms || 0) / totalMs) * 100, 0.8);
    return { left: Math.min(left, 99.2), width: Math.min(width, 100 - Math.min(left, 99.2)) };
  };

  const ticks = [0, 0.25, 0.5, 0.75, 1];
  // Vertical gridlines at each quarter, drawn behind every bar track so they line up.
  const gridBg = "repeating-linear-gradient(90deg, transparent 0, transparent calc(25% - 1px), var(--border) calc(25% - 1px), var(--border) 25%)";

  // Exactly one row must be tabbable, and it has to be one that's mounted — otherwise a cursor
  // that has scrolled out of the window would make Tab skip the whole tree.
  const tabRow = virtual ? Math.min(Math.max(cursor, v.start), Math.max(v.start, v.end - 1)) : cursor;

  const renderRow = ({ span: s, depth }: { span: TraceSpan; depth: number }, i: number) => {
    const b = bar(s);
    const off = offsetMs(s);
    const pct = Math.round(((s.duration_ms || 0) / totalMs) * 100);
    const failed = s.status === "failed";
    const isOpen = open === s.span_id;
    // role=none keeps the measurement wrapper out of the a11y tree, so the button below stays a
    // direct treeitem of the list it's announced in.
    return (
      <div key={s.span_id} role="none" ref={virtual ? v.rowRef(i) : undefined}>
        <button id={rowDomId(s.span_id)} onClick={() => select(i)} onFocus={() => setCursor(i)} style={spanRow(isOpen)}
          role="treeitem" aria-level={depth + 1} aria-expanded={isOpen}
          aria-posinset={i + 1} aria-setsize={rows.length} tabIndex={i === tabRow ? 0 : -1}>
          <span style={{ paddingLeft: depth * 16, display: "inline-flex", alignItems: "center", gap: 8, minWidth: 0, flex: "0 0 42%" }}>
            <span style={badge(s.type)}>{s.type}</span>
            <span style={{ fontSize: 12.5, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{s.label}</span>
          </span>
          <span title={`start +${fmtDur(off)} · ${s.duration_ms}ms · ${pct}% of trace`}
            style={{ position: "relative", flex: 1, height: 16, background: "var(--bg-2)", backgroundImage: gridBg, borderRadius: 4 }}>
            <span style={{ position: "absolute", top: 3, height: 10, borderRadius: 3,
              left: `${b.left}%`, width: `${b.width}%`, minWidth: 3,
              background: failed ? "var(--red)" : heat ? heatColor((s.duration_ms || 0) / maxDur) : (TYPE_COLOR[s.type] || "var(--muted)"),
              opacity: 0.9, boxShadow: isOpen ? "0 0 0 1px var(--text)" : "none" }} />
          </span>
          <span style={{ display: "inline-flex", alignItems: "center", gap: 8, flexShrink: 0 }}>
            {tokens(s) && <span className="muted mono" style={{ fontSize: 10.5 }} title="input → output tokens">{tokens(s)}</span>}
            <span className="mono" style={{ fontSize: 11, width: 58, textAlign: "right", color: failed ? "var(--red)" : "var(--muted)" }}>{fmtDur(s.duration_ms || 0)}</span>
          </span>
        </button>
        {isOpen && (
          <div style={{ padding: `4px 0 10px ${depth * 16 + 14}px` }}>
            {s.request?.model && <div className="muted mono" style={{ fontSize: 11.5, marginBottom: 6 }}>{s.request.model}</div>}
            <SpanBody span={s} fallback={<DefaultBody span={s} />} />
          </div>
        )}
      </div>
    );
  };

  return (
    <div>
      {/* toolbar: latency-heat toggle (mirrors the flow graph), with a legend when on */}
      <div style={{ display: "flex", justifyContent: "flex-end", alignItems: "center", gap: 10, marginBottom: 8 }}>
        {heat && (
          <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 10.5, color: "var(--muted)" }}>
            <span>fast</span>
            <span style={{ width: 54, height: 7, borderRadius: 4, background: `linear-gradient(90deg, ${heatColor(0)}, ${heatColor(0.5)}, ${heatColor(1)})` }} />
            <span>slow · {fmtDur(maxDur)}</span>
          </div>
        )}
        {spans.length > 1 && (
          <button onClick={() => setHeat((v) => !v)} title="Colour bars by latency" style={toggleBtn(heat)}>{heat ? "Heat ✓" : "Heat"}</button>
        )}
      </div>
      {/* time ruler aligned with the bar tracks */}
      <div style={{ display: "flex", alignItems: "center", padding: "0 0 6px", paddingRight: gutter || undefined, fontSize: 10, color: "var(--muted)" }}>
        <span style={{ flex: "0 0 42%" }} />
        <span style={{ position: "relative", flex: 1, height: 12 }}>
          {ticks.map((f) => (
            <span key={f} style={{ position: "absolute", left: `${f * 100}%`,
              transform: f === 1 ? "translateX(-100%)" : f === 0 ? "none" : "translateX(-50%)", whiteSpace: "nowrap" }}>
              {fmtDur(f * totalMs)}
            </span>
          ))}
        </span>
        <span style={{ flex: "0 0 82px" }} />
      </div>
      {/* Row list. Virtualized above VIRTUALIZE_FROM rows: only the visible slice is mounted and
          two spacers hold the scrollbar honest. Below it, every row renders as it always did. */}
      <div role="tree" aria-label="Trace spans" onKeyDown={onKeyDown}
        ref={virtual ? scrollRef : undefined}
        style={virtual ? { maxHeight: "62vh", overflowY: "auto", position: "relative" } : undefined}>
        {virtual && v.padTop > 0 && <div aria-hidden style={{ height: v.padTop }} />}
        {(virtual ? rows.slice(v.start, v.end) : rows).map((r, k) => renderRow(r, virtual ? v.start + k : k))}
        {virtual && v.padBottom > 0 && <div aria-hidden style={{ height: v.padBottom }} />}
      </div>
      {!hasReal && (
        <div className="muted" style={{ fontSize: 11, marginTop: 12, display: "flex", alignItems: "flex-start", gap: 6, lineHeight: 1.5 }}>
          <span style={{ flexShrink: 0 }}>ⓘ</span>
          <span>Approximate timing — no per-span timestamps were captured, so siblings are laid out sequentially. Absolute offsets may differ if some spans actually ran in parallel.</span>
        </div>
      )}
    </div>
  );
}

// Invocation parameters on an LLM span, shown as labelled chips (only if any were captured).
function ParamRow({ params, finish }: { params: any; finish?: any }) {
  const chips: [string, string][] = [];
  if (params?.temperature != null) chips.push(["temp", String(params.temperature)]);
  if (params?.top_p != null) chips.push(["top_p", String(params.top_p)]);
  if (params?.max_tokens != null) chips.push(["max_tokens", String(params.max_tokens)]);
  if (finish != null) chips.push(["finish", String(finish)]);
  if (!chips.length) return null;
  return (
    <div style={{ marginBottom: 8 }}>
      <div className="muted" style={fieldLabel}>Parameters</div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
        {chips.map(([k, v]) => (
          <span key={k} style={{ fontSize: 11.5, fontFamily: "var(--font-mono)", padding: "3px 9px",
            borderRadius: 6, background: "var(--bg-2)", border: "1px solid var(--border)" }}>
            <span className="muted">{k}</span> {v}
          </span>
        ))}
      </div>
    </div>
  );
}

function ErrorBlock({ error }: { error?: string }) {
  return (
    <div style={{ marginBottom: 8 }}>
      <div style={{ fontSize: 10.5, textTransform: "uppercase", letterSpacing: 0.4, marginBottom: 4, color: "var(--red)", fontWeight: 600 }}>
        ✕ Error
      </div>
      <pre style={{ ...pre, border: "1px solid var(--red)", background: "color-mix(in srgb, var(--red) 8%, var(--bg-2))", color: "var(--text)" }}>
        {error?.trim() || <span className="muted">This span failed (no error message captured).</span>}
      </pre>
    </div>
  );
}

const CLAMP = 600;   // chars before we collapse a long payload behind "show more"

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  const str = typeof children === "string" ? children : null;
  const empty = !children || (str != null && !str.trim());
  const long = str != null && str.length > CLAMP;
  const shown = long && !open ? str!.slice(0, CLAMP) + "…" : children;
  return (
    <div style={{ marginBottom: 8 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div className="muted" style={fieldLabel}>{label}</div>
        {long && (
          <button onClick={() => setOpen((o) => !o)} style={{ background: "none", border: "none",
            color: "var(--accent)", fontSize: 11, cursor: "pointer", padding: 0 }}>
            {open ? "Show less" : `Show more (${str!.length.toLocaleString()} chars)`}
          </button>
        )}
      </div>
      <pre style={pre}>{empty ? <span className="muted">—</span> : shown}</pre>
    </div>
  );
}

// Fields the server stripped from this span before sending it (a redacted share link). Read off
// the row rather than inferred from empty content: "withheld" and "the model was called with
// nothing" look identical in the payload, and only one of them is worth telling the reader.
function withheldOf(s: TraceSpan): string[] {
  return (s as unknown as { withheld?: string[] }).withheld || [];
}

function textOf(v: any): string {
  if (v == null) return "";
  return typeof v === "string" ? v : JSON.stringify(v, null, 2);
}

function tokens(s: TraceSpan): string | null {
  const u = s.result?.meta?.usage;
  if (!u || u.input_tokens == null) return null;
  return `${u.input_tokens}→${u.output_tokens ?? 0} tok`;
}

const fieldLabel: React.CSSProperties = {
  fontSize: 10.5, textTransform: "uppercase", letterSpacing: 0.4, marginBottom: 4,
};
const sessionBadge: React.CSSProperties = {
  fontSize: 11, marginLeft: 8, padding: "1px 7px", borderRadius: 5, color: "var(--purple)",
  border: "1px solid var(--border-strong)",
};
function chip(color?: string): React.CSSProperties {
  return {
    fontSize: 11, padding: "2px 8px", borderRadius: 999, color: color || "var(--muted)",
    border: `1px solid ${color ? color : "var(--border)"}`, background: "var(--bg-2)", whiteSpace: "nowrap",
  };
}
const sharePanel: React.CSSProperties = {
  position: "absolute", right: 0, top: "calc(100% + 6px)", zIndex: 20, width: 300,
  background: "var(--panel)", border: "1px solid var(--border-strong)", borderRadius: 10,
  padding: 12, boxShadow: "var(--sh-2)", textAlign: "left",
};
const collapseBtn: React.CSSProperties = {
  position: "absolute", top: 10, zIndex: 5, width: 22, height: 22, borderRadius: 6,
  border: "1px solid var(--border-strong)", background: "var(--panel)", color: "var(--muted)",
  cursor: "pointer", fontSize: 14, lineHeight: 1, display: "grid", placeItems: "center",
};
function insBadge(type: string, status: string): React.CSSProperties {
  const c = status === "failed" ? "var(--red)" : (TYPE_COLOR[type] || "var(--muted)");
  return { fontSize: 9.5, fontWeight: 700, textTransform: "uppercase", letterSpacing: 0.3,
    padding: "1px 5px", borderRadius: 4, color: c, border: `1px solid ${c}`, flexShrink: 0 };
}
function insTab(active: boolean): React.CSSProperties {
  return { fontSize: 12, padding: "6px 10px", background: "none", border: "none", cursor: "pointer",
    color: active ? "var(--text)" : "var(--muted)", fontWeight: active ? 600 : 400,
    borderBottom: `2px solid ${active ? "var(--accent)" : "transparent"}`, marginBottom: -1 };
}
const pre: React.CSSProperties = {
  margin: 0, padding: 10, borderRadius: 8, background: "var(--bg-2)", border: "1px solid var(--border)",
  fontSize: 12, lineHeight: 1.5, fontFamily: "var(--font-mono)", whiteSpace: "pre-wrap",
  wordBreak: "break-word", maxHeight: 240, overflowY: "auto",
};
function spanRow(active: boolean): React.CSSProperties {
  return {
    display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10, width: "100%",
    textAlign: "left", padding: "7px 8px", borderRadius: 7, cursor: "pointer", color: "var(--text)",
    background: active ? "var(--panel-2)" : "transparent", border: "1px solid transparent",
  };
}
function badge(type: string): React.CSSProperties {
  return {
    fontSize: 10, fontWeight: 600, textTransform: "uppercase", letterSpacing: 0.3,
    padding: "2px 6px", borderRadius: 5, flexShrink: 0,
    color: TYPE_COLOR[type] || "var(--muted)", border: `1px solid ${TYPE_COLOR[type] || "var(--border-strong)"}`,
  };
}
