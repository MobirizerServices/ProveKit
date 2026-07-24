"use client";

import Link from "next/link";

/**
 * The shared empty state.
 *
 * Every list page had hand-rolled its own — thirteen of them, each a single grey line ("No
 * datasets yet.") followed, on most, by an instruction to go and write Python. That is a dead
 * end dressed as an explanation: it tells you the page is empty, which you can already see,
 * and then hands the problem back.
 *
 * An empty page is the *first* thing a new account sees on nine of thirteen sections, so it is
 * the most-read screen in the product and was the least designed. This one always answers
 * three things:
 *
 *   what   — what this section holds, in one sentence, since the label alone doesn't say
 *            (nobody can tell Evaluations from Evaluators from the nav)
 *   why    — why it is empty *right now*, which is usually "nothing has created one yet"
 *            rather than anything being broken
 *   next   — one action, and a real one where the page already has a control that does it
 *
 * `action` is deliberately singular. Offering three links from an empty page is how you get a
 * user who reads all three and picks none. Where a page genuinely needs code (a session id has
 * to come from the caller; nothing in the browser can supply it), `code` carries the snippet —
 * but that is the fallback, not the default, and several pages that were telling people to run
 * `pk.evaluate()` in fact had a working button ten pixels away.
 */
export interface EmptyAction {
  label: string;
  href?: string;
  onClick?: () => void;
}

export default function Empty({
  what, why, action, code, note,
}: {
  what: string;
  why?: string;
  action?: EmptyAction;
  code?: string;
  note?: React.ReactNode;
}) {
  return (
    <div className="pk-empty">
      <p className="pk-empty-what">{what}</p>
      {why && <p className="pk-empty-why">{why}</p>}

      {code && <pre className="pk-empty-code mono">{code}</pre>}

      {action && (action.href
        ? <Link href={action.href} className="pk-empty-action">{action.label} →</Link>
        : <button type="button" className="pk-empty-action" onClick={action.onClick}>
            {action.label}
          </button>)}

      {note && <p className="pk-empty-note">{note}</p>}
    </div>
  );
}
