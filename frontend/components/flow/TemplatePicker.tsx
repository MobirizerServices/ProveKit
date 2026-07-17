"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "@/lib/api";
import { useEscape } from "@/lib/useEscape";

type Tmpl = { slug: string; name: string; description: string; category: string };
type Starter = { id: string; name: string; desc: string; icon: string };

export default function TemplatePicker({ starters, onStarter, onTemplate, onClose }: {
  starters: Starter[];
  onStarter: (id: string) => void;
  onTemplate: (slug: string) => Promise<void> | void;
  onClose: () => void;
}) {
  useEscape(onClose);
  const [q, setQ] = useState("");
  const [cat, setCat] = useState("");
  const [total, setTotal] = useState(0);
  const [categories, setCategories] = useState<string[]>([]);
  const [items, setItems] = useState<Tmpl[]>([]);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const timer = useRef<any>(null);

  // debounced search (category is folded into the query)
  useEffect(() => {
    setLoading(true);
    clearTimeout(timer.current);
    let cancelled = false;  // ignore a slow earlier search that resolves after a newer query
    const query = [q, cat].filter(Boolean).join(" ");
    timer.current = setTimeout(() => {
      api.flowTemplates(query, 60).then((r) => {
        if (cancelled) return;
        setItems(r.items); setTotal(r.total);
        if (!categories.length) setCategories(r.categories);
      }).catch(() => { if (!cancelled) setItems([]); }).finally(() => { if (!cancelled) setLoading(false); });
    }, 180);
    return () => { cancelled = true; clearTimeout(timer.current); };
  }, [q, cat]); // eslint-disable-line

  const pick = async (slug: string) => { setBusy(slug); try { await onTemplate(slug); } finally { setBusy(null); } };
  const showStarters = useMemo(() => !q && !cat, [q, cat]);

  return (
    <div className="overlay" onClick={onClose}>
      <div className="modal wiz" role="dialog" aria-modal="true" aria-label="New flow" style={{ width: 680 }} onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">New flow <span className="hint" style={{ fontWeight: 400, marginLeft: 8 }}>{total} templates</span><button onClick={onClose} aria-label="Close">×</button></div>
        <div className="modal-body">
          <input className="tpl-search mono" autoFocus placeholder="Search templates — e.g. triage, extract, sentiment, finance…"
            value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search flow templates" />
          {categories.length > 0 && (
            <div className="tpl-cats">
              <button className={`tpl-chip ${!cat ? "on" : ""}`} onClick={() => setCat("")}>all</button>
              {categories.map((c) => <button key={c} className={`tpl-chip ${cat === c ? "on" : ""}`} onClick={() => setCat(cat === c ? "" : c)}>{c}</button>)}
            </div>
          )}

          {showStarters && (
            <>
              <div className="tpl-label">Start from scratch</div>
              <div className="wiz-grid" style={{ marginBottom: 6 }}>
                {starters.map((t) => (
                  <button key={t.id} className="wiz-provider" onClick={() => onStarter(t.id)}>
                    <span className="wp-ic">{t.icon}</span>
                    <span className="wp-main"><span className="wp-name">{t.name}</span><span className="wp-desc">{t.desc}</span></span>
                    <span className="wp-arrow">›</span>
                  </button>
                ))}
              </div>
              <div className="tpl-label">Or a ready-made template</div>
            </>
          )}

          {loading && items.length === 0 ? (
            <div className="jv-empty" style={{ padding: 24 }}>Searching…</div>
          ) : items.length === 0 ? (
            <div className="jv-empty" style={{ padding: 24 }}>No templates match “{q || cat}”.</div>
          ) : (
            <div className="tpl-list">
              {items.map((t) => (
                <button key={t.slug} className="tpl-item" disabled={busy === t.slug} onClick={() => pick(t.slug)}>
                  <div className="tpl-item-main">
                    <div className="tpl-item-name">{t.name}</div>
                    <div className="tpl-item-desc">{t.description}</div>
                  </div>
                  <span className="tpl-item-cat">{t.category}</span>
                  <span className="wp-arrow">{busy === t.slug ? "…" : "›"}</span>
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
