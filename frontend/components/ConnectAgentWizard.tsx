"use client";

import { useState } from "react";
import { api, Connection, Kind } from "@/lib/api";
import { useEscape } from "@/lib/useEscape";

type Preset = {
  id: string; kind: Kind; provider?: string; name: string; icon: string; desc: string;
  base?: string; models?: string; need: string[];
};

const PRESETS: Preset[] = [
  { id: "openai", kind: "llm", provider: "openai", name: "OpenAI", icon: "⚡", desc: "GPT-4o, GPT-4.1, o-series", base: "https://api.openai.com/v1", models: "gpt-4o-mini, gpt-4o, gpt-4.1-mini", need: ["key"] },
  { id: "openai-responses", kind: "llm", provider: "openai-responses", name: "OpenAI Responses", icon: "◎", desc: "Responses API · vLLM · Ollama · OpenRouter", base: "https://api.openai.com/v1", models: "gpt-4o-mini, gpt-4.1", need: ["key"] },
  { id: "anthropic", kind: "llm", provider: "anthropic", name: "Anthropic", icon: "◈", desc: "Claude Opus, Sonnet, Haiku", base: "https://api.anthropic.com/v1", models: "claude-opus-4-1, claude-sonnet-4-5, claude-haiku-4-5", need: ["key"] },
  { id: "compatible", kind: "llm", provider: "compatible", name: "OpenAI-compatible", icon: "⌘", desc: "Ollama · vLLM · Together · any base URL", base: "", models: "", need: ["base", "key", "models"] },
  { id: "mcp", kind: "mcp", name: "MCP server", icon: "🔧", desc: "Model Context Protocol tools, by URL", need: ["url"] },
  { id: "agent", kind: "agent", name: "HTTP agent", icon: "🛰️", desc: "Any REST / SSE agent endpoint", need: ["base"] },
  { id: "a2a", kind: "a2a", name: "A2A agent", icon: "🤝", desc: "Agent2Agent protocol (agent card + JSON-RPC)", need: ["base"] },
];

export default function ConnectAgentWizard({ onDone, onClose }: { onDone: (c: Connection) => void; onClose: () => void }) {
  useEscape(onClose);
  const [p, setP] = useState<Preset | null>(null);
  const [name, setName] = useState("");
  const [key, setKey] = useState("");
  const [base, setBase] = useState("");
  const [models, setModels] = useState("");
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [created, setCreated] = useState<Connection | null>(null);
  const [test, setTest] = useState<{ ok: boolean; detail: string } | null>(null);

  const pick = (preset: Preset) => {
    setP(preset); setName(preset.name); setBase(preset.base || ""); setModels(preset.models || "");
    setKey(""); setUrl(""); setCreated(null); setTest(null);
  };

  const canConnect = !!p && !!name && (
    p.kind === "mcp" ? !!url :
    (p.kind === "agent" || p.kind === "a2a") ? !!base :
    !!key && (p.provider !== "compatible" || (!!base && !!models))
  );

  async function connect() {
    if (!p) return;
    setBusy(true); setTest(null);
    try {
      let config: any = {};
      if (p.kind === "llm") config = { provider: p.provider, base_url: base, api_key: key, models: models.split(",").map((m) => m.trim()).filter(Boolean) };
      else if (p.kind === "mcp") config = { url };
      else config = { base_url: base, headers: {} };
      const conn = created ?? await api.createConnection({ name, kind: p.kind, config });
      setCreated(conn);
      const t = await api.testConnection(conn.id);
      setTest(t);
    } catch (e: any) {
      setTest({ ok: false, detail: e.message });
    } finally { setBusy(false); }
  }

  return (
    <div className="overlay" onClick={onClose}>
      <div className="modal wiz" role="dialog" aria-modal="true" aria-label="Connect an agent" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          {p && <button className="wiz-back" onClick={() => { setP(null); setCreated(null); setTest(null); }} aria-label="Back" title="Back">‹</button>}
          {p ? `Connect ${p.name}` : "Connect an agent"}
          <button onClick={onClose} aria-label="Close">×</button>
        </div>

        {!p ? (
          <div className="modal-body">
            <p className="wiz-lead">Pick a provider — we’ll prefill everything except your key.</p>
            <div className="wiz-grid">
              {PRESETS.map((x) => (
                <button key={x.id} className="wiz-provider" onClick={() => pick(x)}>
                  <span className="wp-ic">{x.icon}</span>
                  <span className="wp-main"><span className="wp-name">{x.name}</span><span className="wp-desc">{x.desc}</span></span>
                  <span className="wp-arrow">›</span>
                </button>
              ))}
            </div>
          </div>
        ) : (
          <div className="modal-body">
            <div className="field"><label>Name</label><input value={name} onChange={(e) => setName(e.target.value)} /></div>
            {(p.provider === "compatible" || p.kind === "agent" || p.kind === "a2a") && (
              <div className="field"><label>Base URL</label><input className="mono" value={base} onChange={(e) => setBase(e.target.value)} placeholder={p.kind === "agent" || p.kind === "a2a" ? "http://127.0.0.1:8000" : "http://localhost:11434/v1"} /></div>
            )}
            {p.kind === "mcp" && (
              <div className="field"><label>Server URL</label><input className="mono" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="http://127.0.0.1:8765/mcp" /></div>
            )}
            {p.kind === "llm" && (
              <>
                <div className="field"><label>API key</label><input type="password" value={key} onChange={(e) => setKey(e.target.value)} placeholder={p.provider === "anthropic" ? "sk-ant-…" : "sk-…"} /></div>
                {p.provider !== "compatible"
                  ? <div className="wiz-note">Base URL <code>{base}</code> and default models are set for you.</div>
                  : <div className="field"><label>Models <span className="hint">comma-separated</span></label><input className="mono" value={models} onChange={(e) => setModels(e.target.value)} placeholder="llama3.1, mistral" /></div>}
              </>
            )}
            {test && <div className={`wiz-test ${test.ok ? "ok" : "err"}`}><span className="wt-ic">{test.ok ? "✓" : "!"}</span>{test.detail}</div>}
          </div>
        )}

        {p && (
          <div className="modal-foot">
            <button className="btn btn-ghost" onClick={onClose}>Cancel</button>
            {test?.ok
              ? <button className="btn btn-run" onClick={() => created && onDone(created)}>Done →</button>
              : <button className="btn btn-run" disabled={!canConnect || busy} onClick={connect}>{busy ? "Testing…" : created ? "Retry test" : "Connect & test"}</button>}
          </div>
        )}
      </div>
    </div>
  );
}
