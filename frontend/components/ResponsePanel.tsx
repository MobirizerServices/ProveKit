"use client";

import { useState } from "react";
import JsonView from "./JsonView";

export interface AssertResult { type: string; name: string; ok: boolean; detail: string; }
export interface RunState {
  status: "idle" | "running" | "completed" | "failed" | "interrupted";
  text: string;
  output: any;
  meta: any;
  error: string;
  events: any[];
  durationMs: number;
  assertResults: AssertResult[];
}

function usageTokens(usage: any): string | null {
  if (!usage) return null;
  const t = usage.total_tokens ?? ((usage.input_tokens ?? usage.prompt_tokens ?? 0) + (usage.output_tokens ?? usage.completion_tokens ?? 0));
  return t ? `${t} tok` : null;
}

export interface Onboarding { connected: boolean; canRun: boolean; onConnect: () => void; onExample: () => void; onRun: () => void; }

export default function ResponsePanel({ run, onboarding, onAddAssertion }: { run: RunState; onboarding?: Onboarding; onAddAssertion?: (a: any) => void }) {
  const [tab, setTab] = useState<"output" | "raw" | "events" | "assert">("output");
  const { status, text, output, meta, error, events, assertResults } = run;
  const hasStream = !!text;
  const tok = usageTokens(meta?.usage);
  const asserts = assertResults || [];
  const passed = asserts.filter((a) => a.ok).length;
  const done = status === "completed" || status === "failed";

  // Turn the actual run into an assertion — the conversion loop from "I ran it" to "it's a test".
  const assertContains = () => {
    const sel = typeof window !== "undefined" ? String(window.getSelection() || "") : "";
    const value = sel.trim() || (text || (typeof output === "string" ? output : "")).trim().slice(0, 40);
    if (value) onAddAssertion?.({ type: "contains", value });
  };
  const assertLatency = () => onAddAssertion?.({ type: "latency_lt", value: String(Math.ceil((run.durationMs || 100) * 1.5)) });
  const pickJson = (path: string, value: any) => onAddAssertion?.({ type: "json_path", path, value: value == null ? "" : String(value) });

  return (
    <div className="response-pane">
      <div className="resp-head">
        <span className={`resp-status ${status}`}><span className="sdot" />{status}</span>
        <div className="resp-meta">
          {asserts.length > 0 && <span className={`meta-pill ${passed === asserts.length ? "pass" : "fail"}`}>{passed}/{asserts.length} passed</span>}
          {run.durationMs > 0 && <span className="meta-pill">{run.durationMs} ms</span>}
          {meta?.model && <span className="meta-pill">{meta.model}</span>}
          {tok && <span className="meta-pill">{tok}</span>}
          {meta?.tool && <span className="meta-pill">mcp</span>}
          {meta?.status && <span className="meta-pill">HTTP {meta.status}</span>}
        </div>
      </div>

      <div className="resp-tabs">
        <button className={tab === "output" ? "on" : ""} onClick={() => setTab("output")}>Output</button>
        <button className={tab === "raw" ? "on" : ""} onClick={() => setTab("raw")}>Raw</button>
        {asserts.length > 0 && <button className={tab === "assert" ? "on" : ""} onClick={() => setTab("assert")}>Assertions ({passed}/{asserts.length})</button>}
        {events.length > 0 && <button className={tab === "events" ? "on" : ""} onClick={() => setTab("events")}>Events ({events.length})</button>}
        {done && onAddAssertion && !error && (hasStream || output != null) && (
          <div className="resp-assert-bar">
            {(hasStream || typeof output === "string") && <button className="ra-btn" title="Assert the output contains the selected text (or start of the reply)" onClick={assertContains}>+ contains</button>}
            <button className="ra-btn" title="Assert latency below ~1.5× this run" onClick={assertLatency}>+ latency</button>
          </div>
        )}
      </div>

      <div className="resp-body">
        {status === "idle" && !hasStream && output == null && !error ? (
          onboarding ? (
            <div className="resp-welcome">
              <div className="rw-icon">◇</div>
              <h3>Test any agent in seconds</h3>
              <p>Set up a request on the left, then run it. Prompts stream tokens live; tools &amp; agents return structured JSON.</p>
              <div className="rw-actions">
                {!onboarding.connected && <button className="btn btn-run btn-sm" onClick={onboarding.onConnect}>+ Connect an agent</button>}
                <button className="btn btn-sm" onClick={onboarding.onExample}>Insert example</button>
                {onboarding.canRun && <button className="btn btn-run btn-sm" onClick={onboarding.onRun}>▶ Run</button>}
              </div>
              <div className="rw-tips"><span><b>⌘↵</b> run</span><span><b>{"{{var}}"}</b> variables</span><span><b>Save</b> to a collection</span></div>
            </div>
          ) : (
            <div className="resp-empty">
              <div className="big">◇</div>
              Pick a request on the left and hit <b>Run</b>.<br />Prompts stream tokens; tools &amp; agents return structured JSON.
            </div>
          )
        ) : error ? (
          <div className="resp-error">{error}</div>
        ) : tab === "raw" ? (
          <JsonView data={{ output: output ?? (hasStream ? { text } : null), meta }} />
        ) : tab === "assert" ? (
          <div className="assert-results">
            {asserts.map((a, i) => (
              <div key={i} className={`assert-result ${a.ok ? "ok" : "fail"}`}>
                <span className="ar-icon">{a.ok ? "✓" : "✕"}</span>
                <div className="ar-main"><div className="ar-name">{a.name} <span className="ar-type">{a.type}</span></div><div className="ar-detail">{a.detail}</div></div>
              </div>
            ))}
          </div>
        ) : tab === "events" ? (
          <JsonView data={events} />
        ) : hasStream ? (
          <div className="stream-text">{text}{status === "running" && <span className="caret">&nbsp;</span>}</div>
        ) : output != null ? (
          typeof output === "string" ? <div className="stream-text">{output}</div> : <JsonView data={output} onPick={done && onAddAssertion ? pickJson : undefined} />
        ) : status === "running" ? (
          <div className="resp-empty">running…</div>
        ) : (
          <div className="jv-empty">No output.</div>
        )}
      </div>
    </div>
  );
}
