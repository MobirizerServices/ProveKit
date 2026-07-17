"use client";

import { useState } from "react";
import { useEscape } from "@/lib/useEscape";
import { api } from "@/lib/api";

export default function DeployModal({ flowId, flowName, onClose }: { flowId: number; flowName: string; onClose: () => void }) {
  useEscape(onClose);
  const [result, setResult] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [copied, setCopied] = useState("");

  const deploy = async () => {
    setBusy(true); setErr("");
    try { setResult(await api.createDeployment(flowId)); }
    catch (e: any) { setErr(e.message); }
    finally { setBusy(false); }
  };

  const copy = (text: string, what: string) => { navigator.clipboard?.writeText(text); setCopied(what); setTimeout(() => setCopied(""), 1500); };
  const curl = result ? `curl -X POST ${result.url} \\\n  -H "X-API-Key: ${result.api_key ?? "<your-key>"}" \\\n  -H "Content-Type: application/json" \\\n  -d '{"question": "hello"}'` : "";

  return (
    <div className="overlay" onClick={onClose}>
      <div className="modal" role="dialog" aria-modal="true" aria-label="Deploy flow" style={{ width: 620 }} onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">Deploy “{flowName}”<button onClick={onClose} aria-label="Close">×</button></div>
        <div className="modal-body">
          {!result ? (
            <>
              <p className="wiz-lead">Publish this flow as a hosted API endpoint. The current graph is snapshotted — editing the flow later won’t change what’s live until you redeploy.</p>
              {err && <div className="resp-error">{err}</div>}
            </>
          ) : (
            <>
              <div className="field">
                <label>Endpoint <span className="hint">v{result.version}</span></label>
                <div className="dep-copy"><code>{result.url}</code><button className="btn btn-ghost btn-sm" onClick={() => copy(result.url, "url")}>{copied === "url" ? "✓" : "copy"}</button></div>
              </div>
              {result.api_key && (
                <div className="field">
                  <label>API key <span className="hint" style={{ color: "var(--err)" }}>shown once — save it now</span></label>
                  <div className="dep-copy"><code>{result.api_key}</code><button className="btn btn-ghost btn-sm" onClick={() => copy(result.api_key, "key")}>{copied === "key" ? "✓" : "copy"}</button></div>
                </div>
              )}
              <div className="field">
                <label>Try it <button className="btn btn-ghost btn-sm" style={{ marginLeft: "auto" }} onClick={() => copy(curl, "curl")}>{copied === "curl" ? "✓ copied" : "copy"}</button></label>
                <pre className="dep-curl">{curl}</pre>
              </div>
            </>
          )}
        </div>
        <div className="modal-foot">
          <button className="btn btn-ghost" onClick={onClose}>{result ? "Done" : "Cancel"}</button>
          {!result && <button className="btn btn-run" disabled={busy} onClick={deploy}>{busy ? "Deploying…" : "▲ Deploy"}</button>}
        </div>
      </div>
    </div>
  );
}
