"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  api, Flow, FlowGraph, FlowNode, FlowNodeType, FlowRun, FlowVersionSnapshot, ProviderConnection,
} from "@/lib/api";
import ConsoleShell from "@/components/ConsoleShell";
import FlowCanvas, { NODE_META, RunState } from "@/components/FlowCanvas";

const TYPES: FlowNodeType[] = ["trigger", "agent", "model", "knowledge", "logic", "approval", "output"];
const EMPTY: FlowGraph = { nodes: [], edges: [] };

/**
 * Agent Flow Studio — compose a workflow on a canvas, test-run it, publish a version.
 *
 * The draft on the canvas and the published version are deliberately separate: editing here
 * must not change what a published flow does until you say so.
 */
export default function FlowsPage() {
  const [flows, setFlows] = useState<Flow[] | null>(null);
  const [id, setId] = useState<number | null>(null);
  const [graph, setGraph] = useState<FlowGraph>(EMPTY);
  const [selected, setSelected] = useState<string | null>(null);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState("");

  const [runs, setRuns] = useState<FlowRun[]>([]);
  const [versions, setVersions] = useState<FlowVersionSnapshot[]>([]);
  const [conns, setConns] = useState<ProviderConnection[]>([]);
  const [connId, setConnId] = useState("");
  const [testInput, setTestInput] = useState("");
  const [running, setRunning] = useState(false);
  const [lastRun, setLastRun] = useState<FlowRun | null>(null);
  const [tab, setTab] = useState<"build" | "runs" | "versions">("build");
  const [libQ, setLibQ] = useState("");
  // Bumped when a different graph is loaded, so the canvas reseeds; canvas edits never bump it.
  const [rev, setRev] = useState(0);

  const current = flows?.find((f) => f.id === id) || null;

  const loadFlows = useCallback(async () => {
    const rows = await api.flows().catch(() => [] as Flow[]);
    setFlows(rows);
    return rows;
  }, []);

  useEffect(() => { loadFlows().then((rows) => { if (rows.length && id == null) open(rows[0].id); }); }, []);  // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    api.connections().then((cs) => {
      const usable = cs.filter((c) => c.provider !== "mock");
      setConns(usable);
      if (usable[0]) setConnId((v) => v || String(usable[0].id));
    }).catch(() => {});
  }, []);

  const open = async (fid: number) => {
    setId(fid); setSelected(null); setDirty(false); setLastRun(null); setErr("");
    const f = await api.flow(fid).catch(() => null);
    if (f) { setGraph(f.graph || EMPTY); setRev((r) => r + 1); }
    api.flowRuns(fid).then(setRuns).catch(() => setRuns([]));
    api.flowVersions(fid).then(setVersions).catch(() => setVersions([]));
  };

  const create = async () => {
    const name = prompt("Name this flow")?.trim();
    if (!name) return;
    const f = await api.createFlow(name, "", starterGraph());
    await loadFlows();
    open(f.id);
  };

  const save = async () => {
    if (id == null) return;
    setSaving(true); setErr("");
    try { await api.updateFlow(id, { graph }); setDirty(false); await loadFlows(); }
    catch (e) { setErr(msg(e)); }
    finally { setSaving(false); }
  };

  const publish = async () => {
    if (id == null) return;
    setErr("");
    try {
      if (dirty) await api.updateFlow(id, { graph });
      const note = prompt("Publish note (optional)") ?? "";
      await api.publishFlow(id, note);
      setDirty(false);
      await loadFlows();
      api.flowVersions(id).then(setVersions).catch(() => {});
      setTab("versions");
    } catch (e) { setErr(msg(e)); }
  };

  const test = async () => {
    if (id == null) return;
    setRunning(true); setErr(""); setLastRun(null);
    try {
      if (dirty) { await api.updateFlow(id, { graph }); setDirty(false); }
      const r = await api.runFlow(id, {
        input: testInput,
        connection_id: Number(connId),
      });
      setLastRun(r);
      setTab("runs");
      api.flowRuns(id).then(setRuns).catch(() => {});
    } catch (e) { setErr(msg(e)); }
    finally { setRunning(false); }
  };

  const restore = async (version: number) => {
    if (id == null) return;
    const f = await api.restoreFlowVersion(id, version).catch((e) => { setErr(msg(e)); return null; });
    if (f) { setGraph(f.graph || EMPTY); setRev((r) => r + 1); setDirty(false); await loadFlows(); }
  };

  const remove = async () => {
    if (id == null || !confirm("Delete this flow and its runs?")) return;
    await api.deleteFlow(id);
    const rows = await loadFlows();
    setId(null); setGraph(EMPTY);
    if (rows.length) open(rows[0].id);
  };

  // ---- canvas edits --------------------------------------------------------
  const update = (g: FlowGraph) => { setGraph(g); setDirty(true); };

  const addNode = (type: FlowNodeType) => {
    const n: FlowNode = {
      id: `n${Date.now()}`, type, label: NODE_META[type].label,
      position: { x: 120 + (graph.nodes.length % 4) * 240, y: 90 + Math.floor(graph.nodes.length / 4) * 150 },
      config: type === "agent" || type === "model" ? { model: "gpt-4o-mini", prompt: "{{input}}" } : {},
    };
    update({ ...graph, nodes: [...graph.nodes, n] });
    setSelected(n.id);
    setTab("build");
  };

  const node = graph.nodes.find((n) => n.id === selected) || null;
  const patchNode = (patch: Partial<FlowNode>) => {
    if (!node) return;
    update({ ...graph, nodes: graph.nodes.map((n) => (n.id === node.id ? { ...n, ...patch } : n)) });
  };
  const deleteNode = () => {
    if (!node) return;
    update({
      nodes: graph.nodes.filter((n) => n.id !== node.id),
      edges: graph.edges.filter((e) => e.source !== node.id && e.target !== node.id),
    });
    setSelected(null);
  };

  // Colour the canvas by the last run's per-node outcome.
  const runState: RunState = useMemo(() => {
    const out: RunState = {};
    for (const s of lastRun?.steps || []) out[s.node_id] = s.status;
    return out;
  }, [lastRun]);

  return (
    <ConsoleShell>
      {id == null ? (
        /* ── All flows: a gallery of flow cards ── */
        <div className="cs-page fg" style={{ maxWidth: 1180 }}>
          <div className="fg-head">
            <div>
              <div className="page-eyebrow">Visual builder</div>
              <h1>Agent Flows</h1>
              <p className="muted" style={{ fontSize: 13.5, margin: "6px 0 0" }}>
                Compose agents, models, logic and approvals on a canvas, then test-run them with
                trace evidence attached.
              </p>
            </div>
            <button className="btn btn-run" onClick={create}>+ New flow</button>
          </div>
          {flows == null ? <div className="muted" style={{ fontSize: 13 }}>Loading…</div>
            : flows.length === 0 ? (
              <div className="pr-card"><span className="muted">No flows yet. Create one to compose
                your first agent workflow.</span></div>
            ) : (
              <div className="fg-grid">
                {flows.map((f) => (
                  <button key={f.id} className="fg-card" onClick={() => open(f.id)}>
                    <div className="fg-card-top">
                      <span className="fg-card-ic">◆</span>
                      <span className={`fs-pill ${f.published_version ? "pub" : "draft"}`}>
                        {f.published_version ? "Published" : "Draft"}
                      </span>
                    </div>
                    <div className="fg-card-name">{f.name}</div>
                    <div className="fg-card-sub">
                      {(f.graph?.nodes?.length ?? 0)} node{(f.graph?.nodes?.length ?? 0) === 1 ? "" : "s"} · v{f.version}
                      {f.run_count ? ` · ${f.run_count} run${f.run_count === 1 ? "" : "s"}` : ""}
                    </div>
                  </button>
                ))}
              </div>
            )}
        </div>
      ) : (
        /* ── Flow editor: header + Build/Runs/Versions tabs ── */
        <div className="fs2" style={{ height: "calc(100vh - var(--cs-top))" }}>
          <div className="fs-head">
            <button className="fs-back" onClick={() => setId(null)}>‹ All flows</button>
            <h1 className="fs-title">{current?.name}</h1>
            <span className={`fs-pill ${current?.published_version ? "pub" : "draft"}`}>
              {current?.published_version ? "Published" : "Draft"}
            </span>
            <span className="fs-saved">{dirty ? "Unsaved changes" : "All changes saved"}</span>
            <div className="fs-head-actions">
              <button className="btn btn-sm" disabled={!dirty || saving} onClick={save}>
                {saving ? "Saving…" : "Save draft"}
              </button>
              <button className="btn btn-sm" disabled={running} onClick={test}>
                {running ? "Running…" : "▷ Test flow"}
              </button>
              <button className="btn btn-sm btn-run" onClick={publish}>Publish</button>
            </div>
          </div>

          <div className="fs-tabbar">
            <button className={tab === "build" ? "on" : ""} onClick={() => setTab("build")}>Build</button>
            <button className={tab === "runs" ? "on" : ""} onClick={() => setTab("runs")}>
              Runs {runs.length > 0 && <em>{runs.length}</em>}
            </button>
            <button className={tab === "versions" ? "on" : ""} onClick={() => setTab("versions")}>
              Versions {versions.length > 0 && <em>{versions.length}</em>}
            </button>
            <span className="fs-crumb">Flows / {current?.name}</span>
          </div>

          {err && <div className="auth-err" style={{ margin: "10px 16px 0" }}>{err}</div>}

          {tab === "build" ? (
            <div className="fs-build">
              {/* left: node library */}
              <div className="fs-lib">
                <div className="fs-lib-head">Node library<small>Drag or click to add</small></div>
                <input className="fs-lib-search" placeholder="Search nodes…" value={libQ}
                  onChange={(e) => setLibQ(e.target.value)} />
                <div className="fs-lib-group-h">Building blocks</div>
                {TYPES.filter((t) => NODE_META[t].label.toLowerCase().includes(libQ.toLowerCase())).map((t) => (
                  <button key={t} className="fs-lib-item" onClick={() => addNode(t)}>
                    <span className="fs-lib-ic" style={{ background: NODE_META[t].color }}>{NODE_META[t].icon}</span>
                    <span className="fs-lib-main">
                      <span className="fs-lib-name">{NODE_META[t].label}</span>
                      <span className="fs-lib-desc">{NODE_META[t].hint}</span>
                    </span>
                    <span className="fs-lib-add">+</span>
                  </button>
                ))}
              </div>

              {/* center: canvas */}
              <div className="fs-canvas-col">
                <div className="fs-testbar">
                  <input className="flow-input" placeholder="Test input…" value={testInput}
                    onChange={(e) => setTestInput(e.target.value)} />
                  <select className="reg-sel" value={connId} onChange={(e) => setConnId(e.target.value)}>
                    {conns.length === 0
                      ? <option value="">No model connection</option>
                      : conns.map((c) => <option key={c.id} value={String(c.id)}>{c.label || c.provider}</option>)}
                  </select>
                  <button className="btn btn-sm" disabled={running || !connId} onClick={test}
                    title={connId ? "" : "Add a model connection in Settings to test this flow"}>
                    {running ? "Running…" : "▷ Test"}</button>
                  {lastRun && <span className={`fb-status ${lastRun.status}`}>{lastRun.status} · {lastRun.duration_ms}ms</span>}
                </div>
                <FlowCanvas graph={graph} onChange={update} selected={selected}
                  onSelect={(s) => { setSelected(s); setTab("build"); }} runState={runState} revision={rev} />
              </div>

              {/* right: node inspector (Configure) */}
              <div className="node-insp">
                <div className="ni-body">
                  {!node ? (
                    <>
                      <div className="ni-eyebrow">Flow</div>
                      <div className="ni-title" style={{ marginBottom: 12 }}>{current?.name}</div>
                      <p className="muted" style={{ fontSize: 12.5, lineHeight: 1.6 }}>
                        Select a node to configure it, or add one from the library. Drag from a
                        node&apos;s right handle to connect it to the next step.
                      </p>
                      <div className="ni-run" style={{ marginTop: 16 }}>
                        <div className="ni-run-h">Graph</div>
                        <div className="muted" style={{ fontSize: 12.5 }}>
                          {graph.nodes.length} node{graph.nodes.length === 1 ? "" : "s"} ·{" "}
                          {graph.edges.length} connection{graph.edges.length === 1 ? "" : "s"}
                        </div>
                      </div>
                      <button className="btn btn-sm btn-ghost" style={{ marginTop: 18, color: "var(--err)" }}
                        onClick={remove}>Delete flow</button>
                    </>
                  ) : (
                    <>
                      <div className="ni-head-node">
                        <span className="ni-node-ic" style={{ background: NODE_META[node.type].color }}>{NODE_META[node.type].icon}</span>
                        <div>
                          <div className="ni-title">{node.label}</div>
                          <div className="ni-eyebrow">{node.type} node</div>
                        </div>
                      </div>

                      <div className="field" style={{ marginTop: 14 }}>
                        <label>Display name</label>
                        <input value={node.label} onChange={(e) => patchNode({ label: e.target.value })} />
                      </div>

                      {(node.type === "agent" || node.type === "model") && (
                        <>
                          <div className="field">
                            <label>Model</label>
                            <input className="mono" value={node.config?.model || ""} placeholder="gpt-4o-mini"
                              onChange={(e) => patchNode({ config: { ...node.config, model: e.target.value } })} />
                          </div>
                          <div className="field">
                            <label>System instruction <span className="hint">optional</span></label>
                            <textarea rows={3} value={node.config?.system || ""}
                              onChange={(e) => patchNode({ config: { ...node.config, system: e.target.value } })} />
                          </div>
                          <div className="field">
                            <label>Prompt <span className="hint">{"{{input}}"} is the incoming text</span></label>
                            <textarea rows={5} className="mono" value={node.config?.prompt ?? "{{input}}"}
                              onChange={(e) => patchNode({ config: { ...node.config, prompt: e.target.value } })} />
                          </div>
                        </>
                      )}

                      {node.type === "logic" && (
                        <ConditionEditor node={node} onChange={(conditions) =>
                          patchNode({ config: { ...node.config, conditions } })} />
                      )}

                      {node.type === "knowledge" && (
                        <div className="wiz-note">No retriever is configured for this workspace, so this
                          node is skipped at run time rather than returning an invented document.</div>
                      )}
                      {node.type === "approval" && (
                        <div className="wiz-note">A test run auto-approves and records that it did — it
                          can&apos;t block on a reviewer.</div>
                      )}

                      {lastRun?.steps.find((s) => s.node_id === node.id) && (
                        <div className="ni-run">
                          <div className="ni-run-h">Last run</div>
                          <StepDetail step={lastRun.steps.find((s) => s.node_id === node.id)!} />
                        </div>
                      )}

                      <button className="btn btn-sm btn-ghost" style={{ marginTop: 18, color: "var(--err)" }}
                        onClick={deleteNode}>Delete node</button>
                    </>
                  )}
                </div>
              </div>
            </div>
          ) : tab === "runs" ? (
            <div className="fs-tabview">
              {runs.length === 0 ? (
                <div className="pr-card"><span className="muted">No runs yet. Use ▷ Test flow to execute this flow.</span></div>
              ) : (
                <div className="fs-runs">
                  <div className="fr-list">
                    {runs.map((r) => (
                      <button key={r.id} className={`fr-item ${lastRun?.id === r.id ? "on" : ""}`} onClick={() => setLastRun(r)}>
                        <span className={`fr-dot ${r.status}`} />
                        <span className="fr-main">
                          <span className="fr-top">v{r.version} · {r.duration_ms}ms</span>
                          <span className="fr-sub">{r.input || <em>no input</em>}</span>
                        </span>
                        <span className="fr-time">
                          {r.trace_id && <span className="fr-traced" title="Captured as a trace">◇ </span>}
                          {new Date(r.created_at).toLocaleTimeString()}
                        </span>
                      </button>
                    ))}
                  </div>
                  <div className="fs-run-detail">
                    {!lastRun ? <div className="muted" style={{ fontSize: 13, padding: 20 }}>Select a run.</div> : (
                      <>
                        <div className="fr-out-head">
                          <span className="ni-run-h">Output · v{lastRun.version}</span>
                          {lastRun.trace_id
                            ? <a className="btn btn-sm btn-ghost" href={`/traces?trace=${lastRun.trace_id}`}>View trace ↗</a>
                            : <span className="muted" style={{ fontSize: 11 }} title="The run executed; writing its trace did not.">no trace</span>}
                        </div>
                        <div className="fr-out-body" style={{ maxHeight: "none" }}>{lastRun.error || lastRun.output || <span className="muted">empty</span>}</div>
                        <div className="ni-run-h" style={{ marginTop: 16 }}>Steps</div>
                        {(lastRun.steps || []).map((s) => (
                          <div key={s.node_id} className="fs-step-row">
                            <span className={`fr-dot ${s.status === "ok" ? "completed" : s.status === "failed" ? "failed" : "skipped"}`} />
                            <b>{s.label}</b><span className="muted">{s.type} · {s.duration_ms}ms</span>
                            {s.note && <span className="fs-step-note">{s.note}</span>}
                          </div>
                        ))}
                      </>
                    )}
                  </div>
                </div>
              )}
            </div>
          ) : (
            <div className="fs-tabview">
              {versions.length === 0 ? (
                <div className="pr-card"><span className="muted">Nothing published yet. Publishing
                  freezes the current draft as a version you can roll back to.</span></div>
              ) : (
                <div className="fs-versions">
                  {versions.map((v) => (
                    <div key={v.id} className="fv-item">
                      <div>
                        <b>v{v.version}</b>
                        {current?.published_version === v.version && <span className="reg-label production">live</span>}
                        <div className="fr-sub">{v.note || <em>no note</em>}</div>
                        <div className="fr-time">{new Date(v.created_at).toLocaleString()}</div>
                      </div>
                      <button className="btn btn-sm btn-ghost" onClick={() => restore(v.version)}>Restore</button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </ConsoleShell>
  );
}

function StepDetail({ step }: { step: FlowRun["steps"][number] }) {
  return (
    <div className="fs-detail">
      <div className="fs-line">
        <span className={`fr-dot ${step.status === "ok" ? "completed" : step.status === "failed" ? "failed" : "skipped"}`} />
        <span>{step.status}</span>
        <span className="muted">{step.duration_ms}ms</span>
      </div>
      {step.note && <div className="fs-note">{step.note}</div>}
      {step.error && <div className="resp-error" style={{ marginTop: 8 }}>{step.error}</div>}
      {step.output && <div className="fs-out">{step.output}</div>}
    </div>
  );
}

function ConditionEditor({ node, onChange }: {
  node: FlowNode;
  onChange: (c: NonNullable<FlowNode["config"]>["conditions"]) => void;
}) {
  const rows = node.config?.conditions || [];
  const set = (i: number, patch: Partial<{ op: string; value: string; label: string }>) =>
    onChange(rows.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  return (
    <div className="field">
      <label>Conditions <span className="hint">first match wins; the edge label routes it</span></label>
      <div className="vars">
        {rows.map((c, i) => (
          <div key={i} className="cond-row">
            <select value={c.op} onChange={(e) => set(i, { op: e.target.value })}>
              <option value="contains">contains</option>
              <option value="not_contains">not contains</option>
              <option value="equals">equals</option>
              <option value="gt">&gt;</option>
              <option value="lt">&lt;</option>
            </select>
            <input placeholder="value" value={c.value} onChange={(e) => set(i, { value: e.target.value })} />
            <input placeholder="edge label" value={c.label} onChange={(e) => set(i, { label: e.target.value })} />
            <button onClick={() => onChange(rows.filter((_, j) => j !== i))}>×</button>
          </div>
        ))}
      </div>
      <button className="btn btn-sm btn-ghost" style={{ marginTop: 8 }}
        onClick={() => onChange([...rows, { op: "contains", value: "", label: "" }])}>
        + Add condition
      </button>
    </div>
  );
}

/** A new flow opens with a trigger → agent → output skeleton rather than a blank canvas. */
function starterGraph(): FlowGraph {
  return {
    nodes: [
      { id: "n1", type: "trigger", label: "New request", position: { x: 60, y: 160 } },
      { id: "n2", type: "agent", label: "Agent", position: { x: 340, y: 160 },
        config: { model: "gpt-4o-mini", prompt: "{{input}}" } },
      { id: "n3", type: "output", label: "Response", position: { x: 620, y: 160 } },
    ],
    edges: [
      { id: "e1", source: "n1", target: "n2" },
      { id: "e2", source: "n2", target: "n3" },
    ],
  };
}

const msg = (e: unknown) => (e instanceof Error ? e.message : String(e));
