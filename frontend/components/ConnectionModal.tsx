"use client";

import { useState } from "react";
import { useEscape } from "@/lib/useEscape";
import { api, Connection, Kind } from "@/lib/api";

const KINDS: { k: Kind; label: string }[] = [
  { k: "llm", label: "LLM" }, { k: "mcp", label: "MCP server" }, { k: "agent", label: "Agent API" },
];

export default function ConnectionModal({ initial, onSave, onDelete, onClose, onAuthed }: {
  initial?: Connection | null;
  onSave: (c: { id?: number; name: string; kind: Kind; config: any }) => void;
  onDelete?: (id: number) => void;
  onClose: () => void;
  onAuthed?: () => void;
}) {
  useEscape(onClose);
  const [authOpen, setAuthOpen] = useState(false);
  const [loginPath, setLoginPath] = useState("/api/auth/login");
  const [loginBody, setLoginBody] = useState('{ "username": "", "password": "" }');
  const [tokenPath, setTokenPath] = useState("token");
  const [authMsg, setAuthMsg] = useState("");
  const [authErr, setAuthErr] = useState(false);

  const authenticate = async () => {
    if (!initial) return;
    setAuthMsg("authenticating…"); setAuthErr(false);
    try {
      const r = await api.authenticate(initial.id, { login_path: loginPath, method: "POST", body: safeJson(loginBody), token_path: tokenPath });
      setAuthMsg(`✓ token stored on ${r.header} (${r.token})`);
      setTimeout(() => onAuthed?.(), 900);
    } catch (e: any) { setAuthErr(true); setAuthMsg(e.message); }
  };
  const [name, setName] = useState(initial?.name || "");
  const [kind, setKind] = useState<Kind>(initial?.kind || "llm");
  const cfg = initial?.config || {};
  const [provider, setProvider] = useState(cfg.provider || "openai");
  const [baseUrl, setBaseUrl] = useState(cfg.base_url || "");
  const [apiKey, setApiKey] = useState("");
  const [models, setModels] = useState((cfg.models || []).join(", "));
  const [url, setUrl] = useState(cfg.url || "");
  const [headers, setHeaders] = useState(JSON.stringify(cfg.headers || {}, null, 2));

  const save = () => {
    let config: any = {};
    if (kind === "llm") config = { provider, base_url: baseUrl, api_key: apiKey, models: models.split(",").map((m: string) => m.trim()).filter(Boolean) };
    else if (kind === "mcp") config = { url };
    else config = { base_url: baseUrl, headers: safeJson(headers) };
    onSave({ id: initial?.id, name, kind, config });
  };

  return (
    <div className="overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">{initial ? "Edit connection" : "New connection"}<button onClick={onClose} aria-label="Close">×</button></div>
        <div className="modal-body">
          <div className="field"><label>Name</label><input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. OpenAI (prod)" /></div>
          <div className="field">
            <label>Type</label>
            <div className="seg">{KINDS.map((x) => <button key={x.k} className={kind === x.k ? "on" : ""} onClick={() => setKind(x.k)}>{x.label}</button>)}</div>
          </div>

          {kind === "llm" && (
            <>
              <div className="field">
                <label>Provider</label>
                <div className="seg">{["openai", "anthropic", "compatible"].map((p) => <button key={p} className={provider === p ? "on" : ""} onClick={() => setProvider(p)}>{p}</button>)}</div>
              </div>
              <div className="field"><label>Base URL <span className="hint">optional — for compatible/self-hosted</span></label><input className="mono" value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder="https://api.openai.com/v1" /></div>
              <div className="field"><label>API key {initial && <span className="hint">leave blank to keep existing</span>}</label><input type="password" value={apiKey} onChange={(e) => setApiKey(e.target.value)} placeholder={initial?.config?.has_key ? "•••••• (stored)" : "sk-…"} /></div>
              <div className="field"><label>Models <span className="hint">comma-separated</span></label><input className="mono" value={models} onChange={(e) => setModels(e.target.value)} placeholder="gpt-4o-mini, gpt-4o" /></div>
            </>
          )}
          {kind === "mcp" && (
            <div className="field"><label>MCP server URL</label><input className="mono" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="http://127.0.0.1:8765/mcp" /></div>
          )}
          {kind === "agent" && (
            <>
              <div className="field"><label>Base URL</label><input className="mono" value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder="http://127.0.0.1:8000" /></div>
              <div className="field"><label>Default headers <span className="hint">JSON</span></label><textarea className="mono" rows={3} value={headers} onChange={(e) => setHeaders(e.target.value)} placeholder='{ "Authorization": "Bearer …" }' /></div>
              {initial && (
                <div className="auth-box">
                  <div className="auth-head" onClick={() => setAuthOpen((o) => !o)}>
                    <span>🔑 Auth — log in & attach a token</span><span>{authOpen ? "▾" : "▸"}</span>
                  </div>
                  {authOpen && (
                    <div className="auth-body">
                      <div className="hint" style={{ marginBottom: 8 }}>Credentials are used once to fetch a token — only the token (which expires) is saved as a header.</div>
                      <div className="field"><label>Login path</label><input className="mono" value={loginPath} onChange={(e) => setLoginPath(e.target.value)} /></div>
                      <div className="field"><label>Login body <span className="hint">JSON</span></label><textarea className="mono" rows={3} value={loginBody} onChange={(e) => setLoginBody(e.target.value)} /></div>
                      <div className="field"><label>Token path <span className="hint">in the login response</span></label><input className="mono" value={tokenPath} onChange={(e) => setTokenPath(e.target.value)} /></div>
                      <button className="btn btn-run btn-sm" onClick={authenticate}>Authenticate</button>
                      {authMsg && <div className="hint" style={{ marginTop: 8, color: authErr ? "var(--err)" : "var(--ok)" }}>{authMsg}</div>}
                    </div>
                  )}
                </div>
              )}
            </>
          )}
        </div>
        <div className="modal-foot">
          {initial && onDelete && <button className="btn btn-ghost btn-stop" style={{ marginRight: "auto" }} onClick={() => onDelete(initial.id)}>Delete</button>}
          <button className="btn btn-ghost" onClick={onClose}>Cancel</button>
          <button className="btn btn-run" onClick={save} disabled={!name}>Save</button>
        </div>
      </div>
    </div>
  );
}

function safeJson(s: string) { try { return JSON.parse(s); } catch { return {}; } }
