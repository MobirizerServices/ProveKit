"use client";

import { useEffect, useRef, useState } from "react";
import { api, Connection, RunSummary, CollectionT, SavedRequest } from "@/lib/api";
import RequestEditor from "@/components/RequestEditor";
import ResponsePanel, { RunState } from "@/components/ResponsePanel";
import ConnectionModal from "@/components/ConnectionModal";
import ConnectAgentWizard from "@/components/ConnectAgentWizard";
import SaveModal from "@/components/SaveModal";
import DatasetModal from "@/components/DatasetModal";
import CompareModal from "@/components/CompareModal";
import TopNav from "@/components/TopNav";

const IDLE: RunState = { status: "idle", text: "", output: null, meta: {}, error: "", events: [], durationMs: 0, assertResults: [] };

// First-run friendly default: use a real key'd provider if the user has one, otherwise the
// keyless mock agent so a first-time visitor can run something immediately.
function pickDefaultLlm(cs: Connection[]): Connection | undefined {
  const llms = cs.filter((c) => c.kind === "llm");
  return llms.find((c) => c.config?.has_key) || llms.find((c) => c.config?.provider === "mock") || llms[0];
}

export default function Console() {
  const [connections, setConnections] = useState<Connection[]>([]);
  const [collections, setCollections] = useState<{ collections: CollectionT[]; loose: SavedRequest[] }>({ collections: [], loose: [] });
  const [req, setReq] = useState<any>({ type: "prompt", connection_id: null, model: "", system: "", user: "", temperature: 0.7, max_tokens: 1024 });
  const [run, setRun] = useState<RunState>(IDLE);
  const [running, setRunning] = useState(false);
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [tab, setTab] = useState<"collections" | "connections" | "history">("collections");
  const [modal, setModal] = useState<{ conn: Connection | null } | null>(null);
  const [wizard, setWizard] = useState(false);
  const [obDismissed, setObDismissed] = useState(true);
  const [saveModal, setSaveModal] = useState(false);
  const [datasetModal, setDatasetModal] = useState(false);
  const [compareModal, setCompareModal] = useState(false);
  const [toast, setToast] = useState<{ text: string; err?: boolean } | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const canRunRef = useRef(false);
  const doRunRef = useRef<() => void>(() => {});
  const loadK = useRef(0);
  const nextK = () => ++loadK.current;  // bump so type-specific forms remount + reset local buffers on load

  const loadConnections = () => api.connections().then(setConnections).catch(() => {});
  const loadCollections = () => api.collections().then(setCollections).catch(() => {});
  const loadRuns = () => api.runs().then(setRuns).catch(() => {});

  useEffect(() => {
    api.connections().then((cs) => {
      setConnections(cs);
      const llm = pickDefaultLlm(cs);
      if (llm) setReq((r: any) => ({ ...r, connection_id: llm.id, model: (llm.config?.models || [""])[0] || "" }));
    }).catch(() => setToast({ text: "Can't reach the ProveKit backend on :8100", err: true }));
    loadCollections(); loadRuns();
    setObDismissed(typeof localStorage !== "undefined" && localStorage.getItem("agm-onboarded") === "1");
  }, []);

  function onWizardDone(c: Connection) {
    setWizard(false); loadConnections(); setTab("connections");
    if (c.kind === "llm") setReq((r: any) => ({ ...r, type: "prompt", connection_id: c.id, model: (c.config?.models || [""])[0] || "" }));
    flash(`${c.name} connected ✓`);
  }
  const dismissOnboarding = () => { setObDismissed(true); try { localStorage.setItem("agm-onboarded", "1"); } catch {} };

  const flash = (text: string, err = false) => { setToast({ text, err }); setTimeout(() => setToast(null), 2600); };

  async function doRun() {
    setRun({ ...IDLE, status: "running" }); setRunning(true);
    const acc = { text: "", output: null as any, meta: {} as any, events: [] as any[], error: "" };
    const ac = new AbortController(); abortRef.current = ac;
    try {
      await api.runStream(req, (e) => {
        if (e.type === "delta") { acc.text += e.text || ""; setRun((r) => ({ ...r, text: acc.text })); }
        else if (e.type === "result") { acc.output = e.data; acc.meta = e.meta || {}; setRun((r) => ({ ...r, output: acc.output, meta: acc.meta })); }
        else if (e.type === "node") { acc.events.push(e.data); setRun((r) => ({ ...r, events: [...acc.events] })); }
        else if (e.type === "assert") { setRun((r) => ({ ...r, assertResults: e.results || [] })); }
        else if (e.type === "error") { acc.error = e.error || ""; setRun((r) => ({ ...r, error: acc.error })); }
        else if (e.type === "done") { setRun((r) => ({ ...r, status: e.status === "failed" ? "failed" : "completed", durationMs: e.duration_ms || 0 })); }
      }, ac.signal);
    } catch (err: any) {
      if (err?.name !== "AbortError") setRun((r) => ({ ...r, status: "failed", error: String(err?.message || err) }));
    } finally { setRunning(false); abortRef.current = null; loadRuns(); }
  }
  function stop() { abortRef.current?.abort(); setRunning(false); setRun((r) => ({ ...r, status: r.status === "running" ? "interrupted" : r.status })); }

  async function openRun(id: number) {
    try {
      const r = await api.getRun(id);
      setReq({ type: r.type, ...r.request, _k: nextK() });
      const res = r.result || {};
      setRun({ status: r.status === "failed" ? "failed" : "completed", text: res.text || "", output: res.output ?? null, meta: res.meta || {}, error: r.error || "", events: res.events || [], durationMs: r.duration_ms || 0, assertResults: res.assertions || [] });
    } catch { flash("Couldn't load run", true); }
  }
  async function loadRequest(rid: number) {
    try { const r = await api.getRequest(rid); setReq({ type: r.type, ...(r.payload || {}), _k: nextK() }); setRun(IDLE); }
    catch { flash("Couldn't load request", true); }
  }

  async function saveConnection(c: any) {
    try { if (c.id) await api.updateConnection(c.id, c); else await api.createConnection(c); await loadConnections(); setModal(null); flash("Connection saved"); }
    catch (e: any) { flash(e.message, true); }
  }
  async function deleteConnection(id: number) {
    try { await api.deleteConnection(id); await loadConnections(); setModal(null); flash("Connection deleted"); }
    catch (e: any) { flash(e.message, true); }
  }

  const [testing, setTesting] = useState<number | null>(null);
  async function testConn(id: number, e?: React.MouseEvent) {
    e?.stopPropagation(); setTesting(id);
    try { const r = await api.testConnection(id); flash(r.detail, !r.ok); }
    catch (err: any) { flash(err.message, true); }
    finally { setTesting(null); }
  }
  function insertExample() {
    const llm = pickDefaultLlm(connections);
    const mock = llm?.config?.provider === "mock";
    setReq({ type: "prompt", connection_id: llm?.id ?? req.connection_id, model: (llm?.config?.models || [req.model])[0] || req.model,
      system: "You are a helpful, concise assistant.", user: "What is an AI agent?", temperature: 0.7, max_tokens: 1024 });
    setRun(IDLE); flash(mock ? "Example loaded on the demo agent — hit Run" : "Example loaded — hit Run");
  }

  // ⌘↵ to run from anywhere in the console (via refs so it never captures a stale request/handler)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if ((e.metaKey || e.ctrlKey) && e.key === "Enter" && canRunRef.current) { e.preventDefault(); doRunRef.current(); } };
    window.addEventListener("keydown", onKey); return () => window.removeEventListener("keydown", onKey);
  }, []);
  // Abort any in-flight run stream on unmount (no setState-after-unmount / leaked reader).
  useEffect(() => () => abortRef.current?.abort(), []);

  const canRun = !running && !!req.connection_id && (req.type !== "tool" || !!req.tool);
  canRunRef.current = canRun;
  doRunRef.current = doRun;
  const connName = connections.find((c) => c.id === req.connection_id)?.name || "no connection";

  // Onboarding progress: connect an agent → run a request → save it
  const connected = connections.some((c) => c.config?.has_key || (c.kind === "mcp" && c.config?.url) || (c.kind === "agent" && c.config?.base_url));
  const ran = runs.length > 0;
  const saved = collections.collections.some((c) => c.requests.length) || collections.loose.length > 0;
  const showBanner = !obDismissed && !(connected && ran && saved);
  const steps = [
    { n: "1", label: "Connect an agent", done: connected },
    { n: "2", label: "Run a request", done: ran },
    { n: "3", label: "Save it", done: saved },
  ];
  const curStep = steps.findIndex((s) => !s.done);

  return (
    <div className="app" style={{ gridTemplateRows: showBanner ? "auto auto 1fr" : "auto 1fr" }}>
      <TopNav />

      {showBanner && (
        <div className="ob-banner">
          <span className="ob-title">Get started</span>
          <ol className="ob-steps">
            {steps.map((s, i) => (
              <li key={s.n} className={s.done ? "done" : i === curStep ? "cur" : ""}>
                <i>{s.done ? "✓" : s.n}</i>{s.label}
              </li>
            ))}
          </ol>
          {!connected && <button className="btn btn-run btn-sm" onClick={() => setWizard(true)}>Connect an agent</button>}
          <button className="ob-x" onClick={dismissOnboarding} title="Dismiss">×</button>
        </div>
      )}

      <div className="workspace">
        <aside className="sidebar">
          <div className="side-tabs">
            <button className={tab === "collections" ? "on" : ""} onClick={() => { setTab("collections"); loadCollections(); }}>Collections</button>
            <button className={tab === "connections" ? "on" : ""} onClick={() => setTab("connections")}>Connections</button>
            <button className={tab === "history" ? "on" : ""} onClick={() => { setTab("history"); loadRuns(); }}>History</button>
          </div>
          <div className="side-scroll">
            {tab === "collections" && (
              <>
                {collections.collections.length === 0 && collections.loose.length === 0 &&
                  <div className="side-empty"><div className="se-ic">◷</div>No saved requests yet.<br />Build a request, then hit <b>Save</b> to keep it here.</div>}
                {collections.collections.map((c) => (
                  <div className="col-group" key={c.id}>
                    <div className="col-name">{c.name}<span style={{ color: "var(--faint)" }}>{c.requests.length}</span></div>
                    {c.requests.map((r) => <ReqRow key={r.id} r={r} onOpen={loadRequest} onDelete={async (id) => { await api.deleteRequest(id); loadCollections(); }} />)}
                  </div>
                ))}
                {collections.loose.length > 0 && (
                  <div className="col-group">
                    <div className="col-name">Loose</div>
                    {collections.loose.map((r) => <ReqRow key={r.id} r={r} onOpen={loadRequest} onDelete={async (id) => { await api.deleteRequest(id); loadCollections(); }} />)}
                  </div>
                )}
              </>
            )}
            {tab === "connections" && (
              <>
                <div className="side-head"><span>Providers</span><button onClick={() => setWizard(true)} title="Connect an agent">+</button></div>
                <button className="btn btn-run btn-sm" style={{ width: "100%", marginBottom: 10 }} onClick={() => setWizard(true)}>+ Connect an agent</button>
                {connections.map((c) => (
                  <div key={c.id} className="conn-item" onClick={() => setModal({ conn: c })}>
                    <span className={`dot ${c.kind}`} />
                    <div className="ci-main"><div className="ci-name">{c.name}</div><div className="ci-sub">{c.kind === "llm" ? c.config?.provider : c.kind === "mcp" ? c.config?.url : c.config?.base_url}</div></div>
                    <button className="ci-test" title="Test connection" onClick={(e) => testConn(c.id, e)} disabled={testing === c.id}>{testing === c.id ? "…" : "test"}</button>
                    <button className="ci-edit" aria-label="Edit connection" title="Edit">✎</button>
                  </div>
                ))}
              </>
            )}
            {tab === "history" && (
              <>
                <div className="side-head"><span>Recent runs</span><button onClick={loadRuns} title="Refresh">↻</button></div>
                {runs.length === 0 && <div className="side-empty"><div className="se-ic">↻</div>No runs yet.<br />Every request you run lands here — click one to replay it.</div>}
                {runs.map((r) => (
                  <div key={r.id} className="run-item" onClick={() => openRun(r.id)}>
                    <span className="rn-label">{r.label || r.type}</span>
                    <span className="rn-meta"><span className={`tag ${r.type}`}>{r.type}</span><span className={`tag ${r.status}`}>{r.status === "completed" ? "ok" : r.status}</span></span>
                  </div>
                ))}
              </>
            )}
          </div>
        </aside>

        <section className="request-pane">
          <RequestEditor req={req} setReq={setReq} connections={connections} />
          <div className="runbar">
            {running ? <button className="btn btn-stop" onClick={stop}>■ Stop</button> : <button className="btn btn-run" disabled={!canRun} onClick={doRun}>▶ Run</button>}
            <button className="btn btn-ghost btn-sm" onClick={() => setSaveModal(true)}>Save</button>
            <button className="btn btn-ghost btn-sm" disabled={!req.connection_id} onClick={() => setDatasetModal(true)}>Dataset</button>
            {req.type === "prompt" && <button className="btn btn-ghost btn-sm" disabled={!req.connection_id} onClick={() => setCompareModal(true)}>Compare</button>}
            <span className="tb-hint" style={{ marginLeft: "auto" }}>{req.type} · {connName}</span>
          </div>
        </section>

        <ResponsePanel run={run} onboarding={{ connected, canRun, onConnect: () => setWizard(true), onExample: insertExample, onRun: doRun }}
          onAddAssertion={(a) => { setReq((r: any) => ({ ...r, assertions: [...(r.assertions || []), a] })); flash(`Added ${a.type} assertion — run again to check`); }} />
      </div>

      {wizard && <ConnectAgentWizard onDone={onWizardDone} onClose={() => setWizard(false)} />}
      {modal && <ConnectionModal initial={modal.conn} onSave={saveConnection} onDelete={deleteConnection} onClose={() => setModal(null)} onAuthed={() => { loadConnections(); setModal(null); flash("Authenticated ✓ token attached"); }} />}
      {saveModal && <SaveModal collections={collections.collections} req={req} onSaved={() => { loadCollections(); flash("Request saved"); }} onClose={() => setSaveModal(false)} />}
      {datasetModal && <DatasetModal request={req} onClose={() => setDatasetModal(false)} />}
      {compareModal && <CompareModal request={req} connections={connections} onClose={() => setCompareModal(false)} />}
      {toast && <div role="status" aria-live="polite" className={`toast ${toast.err ? "err" : ""}`}>{toast.text}</div>}
    </div>
  );
}

function ReqRow({ r, onOpen, onDelete }: { r: SavedRequest; onOpen: (id: number) => void; onDelete: (id: number) => void }) {
  return (
    <div className="req-item" onClick={() => onOpen(r.id)}>
      <span className={`dot ${r.type}`} />
      <div className="ri-main"><div className="ri-name">{r.name}</div></div>
      <button className="ri-x" aria-label="Delete request" onClick={(e) => { e.stopPropagation(); onDelete(r.id); }}>×</button>
    </div>
  );
}
