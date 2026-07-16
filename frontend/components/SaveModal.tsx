"use client";

import { useState } from "react";
import { useEscape } from "@/lib/useEscape";
import { api, CollectionT } from "@/lib/api";

export default function SaveModal({ collections, req, onSaved, onClose }: {
  collections: CollectionT[]; req: any; onSaved: () => void; onClose: () => void;
}) {
  useEscape(onClose);
  const [name, setName] = useState(defaultName(req));
  const [colId, setColId] = useState<string>(collections[0] ? String(collections[0].id) : "none");
  const [newCol, setNewCol] = useState("");

  const save = async () => {
    let collection_id: number | null = null;
    if (colId === "new" && newCol.trim()) collection_id = (await api.createCollection(newCol.trim())).id;
    else if (colId !== "none" && colId !== "new") collection_id = +colId;
    const { type, ...payload } = req;
    await api.saveRequest({ name: name || "request", type, payload: req, collection_id });
    onSaved(); onClose();
  };

  return (
    <div className="overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">Save request<button onClick={onClose}>×</button></div>
        <div className="modal-body">
          <div className="field"><label>Name</label><input value={name} onChange={(e) => setName(e.target.value)} autoFocus /></div>
          <div className="field">
            <label>Collection</label>
            <select value={colId} onChange={(e) => setColId(e.target.value)}>
              <option value="none">— none (loose) —</option>
              {collections.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              <option value="new">+ New collection…</option>
            </select>
          </div>
          {colId === "new" && <div className="field"><label>New collection name</label><input value={newCol} onChange={(e) => setNewCol(e.target.value)} placeholder="e.g. Sales prompts" /></div>}
        </div>
        <div className="modal-foot">
          <button className="btn btn-ghost" onClick={onClose}>Cancel</button>
          <button className="btn btn-run" onClick={save} disabled={!name}>Save</button>
        </div>
      </div>
    </div>
  );
}

function defaultName(req: any): string {
  if (req.type === "prompt") return (req.user || "prompt").slice(0, 40);
  if (req.type === "tool") return req.tool || "tool";
  if (req.type === "agent") return `${req.method || "POST"} ${req.path || ""}`.trim();
  return "request";
}
