import Link from "next/link";
import React from "react";

// A tiny, dependency-free Markdown renderer for our own blog content (a known, trusted
// subset): ## / ### headings, fenced ``` code blocks, - lists, > quotes, paragraphs, and
// inline `code`, **bold**, and [links](url). Not a general-purpose parser.

function inline(text: string, keyBase: string): React.ReactNode[] {
  // Split on `code`, **bold**, and [label](href) while keeping the delimiters.
  const parts = text.split(/(`[^`]+`|\*\*[^*]+\*\*|\[[^\]]+\]\([^)]+\))/g);
  return parts.filter(Boolean).map((p, i) => {
    const key = `${keyBase}-${i}`;
    if (p.startsWith("`") && p.endsWith("`")) return <code key={key} className="md-code">{p.slice(1, -1)}</code>;
    if (p.startsWith("**") && p.endsWith("**")) return <strong key={key}>{p.slice(2, -2)}</strong>;
    const link = p.match(/^\[([^\]]+)\]\(([^)]+)\)$/);
    if (link) {
      const [, label, href] = link;
      const internal = href.startsWith("/");
      return internal
        ? <Link key={key} href={href} className="md-link">{label}</Link>
        : <a key={key} href={href} className="md-link" target="_blank" rel="noreferrer">{label}</a>;
    }
    return <React.Fragment key={key}>{p}</React.Fragment>;
  });
}

export default function Markdown({ source }: { source: string }) {
  const lines = source.replace(/\r\n/g, "\n").split("\n");
  const out: React.ReactNode[] = [];
  let i = 0;
  let k = 0;
  while (i < lines.length) {
    const line = lines[i];

    if (line.startsWith("```")) {                       // fenced code block
      const lang = line.slice(3).trim();
      const buf: string[] = [];
      i++;
      while (i < lines.length && !lines[i].startsWith("```")) { buf.push(lines[i]); i++; }
      i++; // closing fence
      out.push(<pre key={k++} className="md-pre" data-lang={lang}><code>{buf.join("\n")}</code></pre>);
      continue;
    }
    if (line.startsWith("### ")) { out.push(<h3 key={k++} className="md-h3">{inline(line.slice(4), `h3${k}`)}</h3>); i++; continue; }
    if (line.startsWith("## ")) { out.push(<h2 key={k++} className="md-h2">{inline(line.slice(3), `h2${k}`)}</h2>); i++; continue; }
    if (line.startsWith("> ")) {
      const buf: string[] = [];
      while (i < lines.length && lines[i].startsWith("> ")) { buf.push(lines[i].slice(2)); i++; }
      out.push(<blockquote key={k++} className="md-quote">{inline(buf.join(" "), `q${k}`)}</blockquote>);
      continue;
    }
    if (line.startsWith("- ")) {
      const items: string[] = [];
      while (i < lines.length && lines[i].startsWith("- ")) { items.push(lines[i].slice(2)); i++; }
      out.push(<ul key={k++} className="md-ul">{items.map((it, j) => <li key={j}>{inline(it, `li${k}-${j}`)}</li>)}</ul>);
      continue;
    }
    if (line.trim() === "") { i++; continue; }
    // paragraph: gather consecutive non-empty, non-special lines
    const buf: string[] = [];
    while (i < lines.length && lines[i].trim() !== "" && !/^(#|`{3}|- |> )/.test(lines[i])) { buf.push(lines[i]); i++; }
    out.push(<p key={k++} className="md-p">{inline(buf.join(" "), `p${k}`)}</p>);
  }
  return <div className="md">{out}</div>;
}
