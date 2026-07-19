"use client";

import React, { useState } from "react";

// A minimal, dependency-free highlighter for our own snippets (Python / bash / JSON / TS).
// Colors comments, strings, numbers, and a shared keyword set — good enough for a blog.
const KW = new Set([
  "def", "class", "import", "from", "as", "return", "with", "for", "while", "if", "elif",
  "else", "try", "except", "finally", "async", "await", "lambda", "yield", "in", "not",
  "and", "or", "is", "None", "True", "False", "function", "const", "let", "var", "new",
  "export", "default", "assert", "pip", "install", "git", "cd", "docker", "clone",
]);

const TOKEN = /(#[^\n]*|\/\/[^\n]*)|("(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*'|`(?:[^`\\]|\\.)*`)|(\b\d[\d._]*\b)|([A-Za-z_][A-Za-z0-9_]*)/g;

function highlight(code: string): React.ReactNode[] {
  const out: React.ReactNode[] = [];
  let last = 0;
  let m: RegExpExecArray | null;
  let i = 0;
  TOKEN.lastIndex = 0;
  while ((m = TOKEN.exec(code))) {
    if (m.index > last) out.push(<React.Fragment key={i++}>{code.slice(last, m.index)}</React.Fragment>);
    const cls = m[1] ? "hl-cm" : m[2] ? "hl-st" : m[3] ? "hl-nu" : (m[4] && KW.has(m[4]) ? "hl-kw" : "");
    out.push(cls ? <span key={i++} className={cls}>{m[0]}</span> : <React.Fragment key={i++}>{m[0]}</React.Fragment>);
    last = TOKEN.lastIndex;
  }
  if (last < code.length) out.push(<React.Fragment key={i++}>{code.slice(last)}</React.Fragment>);
  return out;
}

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
      <pre className="md-pre" data-lang={lang}><code>{highlight(code)}</code></pre>
    </div>
  );
}
