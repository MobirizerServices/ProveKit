"use client";

import { useState } from "react";

export default function CodeBlock({ code, lang }: { code: string; lang?: string }) {
  const [copied, setCopied] = useState(false);
  const copy = () => {
    navigator.clipboard?.writeText(code);
    setCopied(true);
    setTimeout(() => setCopied(false), 1400);
  };
  return (
    <div className="md-pre-wrap">
      <button className="md-copy" onClick={copy} aria-label="Copy code">{copied ? "Copied" : "Copy"}</button>
      <pre className="md-pre" data-lang={lang}><code>{code}</code></pre>
    </div>
  );
}
