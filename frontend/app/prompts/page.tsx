"use client";

import { useEffect, useState } from "react";
import { api, PromptT } from "@/lib/api";
import TopNav from "@/components/TopNav";

export default function PromptsPage() {
  const [prompts, setPrompts] = useState<PromptT[]>([]);
  const [toast, setToast] = useState<string | null>(null);
  const load = () => api.prompts().then(setPrompts).catch(() => {});
  useEffect(() => { load(); }, []);
  const flash = (t: string) => { setToast(t); setTimeout(() => setToast(null), 2200); };

  const addNew = async () => {
    try { await api.createPrompt({ name: "New prompt", content: "" }); load(); }
    catch (e: any) { flash(e.message); }
  };

  return (
    <div className="app" style={{ gridTemplateRows: "auto 1fr" }}>
      <TopNav />
      <div className="page">
        <div className="page-inner">
          <div className="page-head">
            <div>
              <div className="page-eyebrow">Registry</div>
              <h1>Prompt Registry</h1>
              <p>Reusable prompts you can reference in flows and requests. Edit and save — changes are live.</p>
            </div>
            <div className="spacer" />
            <button className="btn btn-run" onClick={addNew}>+ New prompt</button>
          </div>
          {prompts.length === 0 && <div className="jv-empty" style={{ padding: 40, textAlign: "center" }}>No prompts yet. Create one to get started.</div>}
          {prompts.map((p) => <PromptCard key={p.id} prompt={p} onSaved={() => { load(); flash("Saved"); }} onDeleted={() => { load(); flash("Deleted"); }} />)}
        </div>
      </div>
      {toast && <div role="status" aria-live="polite" className="toast">{toast}</div>}
    </div>
  );
}

function PromptCard({ prompt, onSaved, onDeleted }: { prompt: PromptT; onSaved: () => void; onDeleted: () => void }) {
  const [name, setName] = useState(prompt.name);
  const [key, setKey] = useState(prompt.key);
  const [desc, setDesc] = useState(prompt.description);
  const [content, setContent] = useState(prompt.content);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState("");
  const dirty = name !== prompt.name || key !== prompt.key || desc !== prompt.description || content !== prompt.content;

  const save = async () => { setSaving(true); setErr(""); try { await api.updatePrompt(prompt.id, { name, key, description: desc, content }); onSaved(); } catch (e: any) { setErr(e.message); } finally { setSaving(false); } };
  const del = async () => { if (confirm(`Delete prompt "${name}"?`)) { try { await api.deletePrompt(prompt.id); onDeleted(); } catch (e: any) { setErr(e.message); } } };

  return (
    <div className="pr-card">
      <div className="pr-top">
        <span className="pr-key"><input value={key} onChange={(e) => setKey(e.target.value)} /></span>
        <span className="pr-updated">{prompt.updated_at ? new Date(prompt.updated_at).toLocaleDateString() : ""}</span>
      </div>
      <input className="pr-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="Prompt name" />
      <input className="pr-desc" value={desc} onChange={(e) => setDesc(e.target.value)} placeholder="What is this prompt for?" />
      <textarea value={content} onChange={(e) => setContent(e.target.value)} placeholder="The prompt text… use {{variables}} for slots." spellCheck={false} />
      <div className="pr-actions">
        <button className="btn btn-run btn-sm" disabled={!dirty || saving} onClick={save}>{saving ? "Saving…" : "Save"}</button>
        <button className="btn btn-ghost btn-sm btn-stop" onClick={del}>Delete</button>
        {dirty && <span className="pr-dirty">● unsaved</span>}
        {err && <span className="hint" style={{ color: "var(--err)" }}>{err}</span>}
      </div>
    </div>
  );
}
