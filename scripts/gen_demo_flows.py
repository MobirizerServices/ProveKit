#!/usr/bin/env python3
"""Generate a gallery of demo agent flows as .agentman files.

Produces 100+ distinct, valid flow templates across real patterns (linear prompt,
classify-then-route, extract-then-validate, tool-then-branch, two-step chains, agent
calls, moderation gates, ...) over a range of domains. Every file validates via
agentman.services.testfile.load. Connections are referenced by name so the files import
into any workspace.

    python scripts/gen_demo_flows.py            # writes examples/.agentman/flows/*.yaml
"""
from __future__ import annotations

import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "backend"))
from agentman.services import testfile  # noqa: E402

OUT = pathlib.Path(__file__).resolve().parent.parent / "examples" / ".agentman" / "flows"
LLM = "Demo Assistant (mock)"   # seeded, keyless — every flow runs offline out of the box
MODEL = "demo-mock"

# (domain, input field, a representative sample value)
DOMAINS = [
    ("customer support", "message", "URGENT: my order never arrived and I want a refund"),
    ("sales lead", "message", "We're a 200-person team evaluating your Pro plan for Q3"),
    ("IT helpdesk", "ticket", "Laptop won't connect to VPN after the update"),
    ("content moderation", "text", "This product is garbage and so is everyone who made it"),
    ("recruiting", "resume", "10y backend, led a payments team, Go and Postgres"),
    ("healthcare intake", "note", "Patient reports headache and mild fever for two days"),
    ("finance", "transaction", "Wire of $48,200 to a new payee in another country"),
    ("legal intake", "inquiry", "Landlord kept my deposit after I moved out on time"),
    ("e-commerce", "review", "Arrived a day late but the quality is excellent, 5 stars"),
    ("travel", "request", "Cheapest flight NYC to Lisbon in the first week of May"),
    ("education", "question", "Explain gradient descent to a first-year student"),
    ("real estate", "listing", "2BR condo downtown, needs a quick sale, motivated seller"),
    ("logistics", "shipment", "Container held at customs, ETA slipped by four days"),
    ("marketing", "brief", "Launch email for a privacy-first note-taking app"),
    ("developer tooling", "issue", "Build fails intermittently on CI, passes locally"),
    ("insurance", "claim", "Rear-ended at a stoplight, minor bumper damage, have photos"),
    ("HR", "feedback", "My manager cancels our 1:1s and I feel blocked on growth"),
    ("research", "abstract", "A new method for retrieval-augmented generation over tables"),
    ("gaming support", "report", "Got disconnected mid-match and lost my rank points"),
    ("food delivery", "complaint", "Order was cold and missing the drinks"),
    ("nonprofit", "message", "We'd like to volunteer 20 people for the weekend drive"),
    ("devrel", "question", "Does your API support streaming responses over websockets?"),
    ("community forum", "post", "Anyone else seeing timeouts on the new release?"),
    ("banking", "request", "I need to dispute a charge I don't recognize on my card"),
]

# Reusable node/edge builders ------------------------------------------------
def N(nid, ntype, title, x, y, config=None):
    return {"id": nid, "type": ntype, "position": {"x": x, "y": y},
            "data": {"title": title}, "config": config or {}}


def prompt_node(nid, title, x, y, system, user):
    return N(nid, "prompt", title, x, y,
             {"connection": LLM, "model": MODEL, "system": system, "user": user})


def E(s, t, branch=None):
    e = {"id": f"e-{s}-{t}", "source": s, "target": t}
    if branch:
        e["condition"] = {"branch": branch}
    return e


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


# Flow-shape builders: each returns (name, description, nodes, edges) ---------
def shape_answer(domain, field, sample):
    return (
        f"{domain.title()} · answer",
        f"Read a {field}, draft a helpful reply.",
        [N("in", "input", "Input", 40, 160, {"sample": {field: sample}}),
         prompt_node("ans", "Draft reply", 340, 160,
                     f"You are a concise {domain} assistant.", f"{{{{input.{field}}}}}"),
         N("out", "output", "Reply", 640, 160, {"value": "{{ans.text}}"})],
        [E("in", "ans"), E("ans", "out")])


def shape_classify_route(domain, field, sample):
    return (
        f"{domain.title()} · triage & route",
        f"Draft a reply, then route urgent vs normal on a keyword check.",
        [N("in", "input", "Input", 40, 200, {"sample": {field: sample}}),
         prompt_node("reply", "Draft", 320, 200,
                     f"You are a {domain} assistant. Note anything urgent.", f"{{{{input.{field}}}}}"),
         N("cond", "condition", "Urgent?", 620, 200, {"left": "{{reply.text}}", "op": "contains", "right": "urgent"}),
         N("human", "output", "Human review", 900, 110, {"value": "escalate: {{reply.text}}"}),
         N("auto", "output", "Auto-send", 900, 300, {"value": "{{reply.text}}"})],
        [E("in", "reply"), E("reply", "cond"), E("cond", "human", "true"), E("cond", "auto", "false")])


def shape_extract_validate(domain, field, sample):
    return (
        f"{domain.title()} · extract to JSON",
        f"Extract structured fields from a {field} as JSON.",
        [N("in", "input", "Input", 40, 160, {"sample": {field: sample}}),
         prompt_node("ex", "Extract", 340, 160,
                     "Extract the key fields. Return ONLY valid JSON, null when absent.",
                     f"Extract from: {{{{input.{field}}}}}"),
         N("out", "output", "JSON", 640, 160, {"value": "{{ex.text}}"})],
        [E("in", "ex"), E("ex", "out")])


def shape_classify_label(domain, field, sample):
    return (
        f"{domain.title()} · classify intent",
        f"Classify a {field} into one label.",
        [N("in", "input", "Input", 40, 160, {"sample": {field: sample}}),
         prompt_node("cls", "Classify", 340, 160,
                     "Classify into exactly one of: urgent, question, complaint, other. Reply with only the label.",
                     f"{{{{input.{field}}}}}"),
         N("out", "output", "Label", 640, 160, {"value": "{{cls.text}}"})],
        [E("in", "cls"), E("cls", "out")])


def shape_summarize_then_act(domain, field, sample):
    return (
        f"{domain.title()} · summarize then decide",
        f"Summarize a {field}, then branch on whether it needs follow-up.",
        [N("in", "input", "Input", 40, 200, {"sample": {field: sample}}),
         prompt_node("sum", "Summarize", 300, 200, "Summarize in one sentence.", f"{{{{input.{field}}}}}"),
         prompt_node("dec", "Needs follow-up?", 560, 200,
                     "Answer yes or no: does this need a human follow-up? Reply with only yes or no.",
                     "{{sum.text}}"),
         N("cond", "condition", "Follow up?", 820, 200, {"left": "{{dec.text}}", "op": "contains", "right": "yes"}),
         N("y", "output", "Queue follow-up", 1080, 110, {"value": "follow-up: {{sum.text}}"}),
         N("n", "output", "Close", 1080, 300, {"value": "resolved: {{sum.text}}"})],
        [E("in", "sum"), E("sum", "dec"), E("dec", "cond"), E("cond", "y", "true"), E("cond", "n", "false")])


def shape_moderate_gate(domain, field, sample):
    return (
        f"{domain.title()} · moderation gate",
        f"Check a {field} for policy issues before publishing.",
        [N("in", "input", "Input", 40, 200, {"sample": {field: sample}}),
         prompt_node("mod", "Moderate", 300, 200,
                     "Reply with 'flag' if the text is abusive or unsafe, else 'ok'. Only that word.",
                     f"{{{{input.{field}}}}}"),
         N("cond", "condition", "Flagged?", 560, 200, {"left": "{{mod.text}}", "op": "contains", "right": "flag"}),
         N("block", "output", "Blocked", 820, 110, {"value": "blocked for review"}),
         N("pub", "output", "Published", 820, 300, {"value": "{{input.%s}}" % field})],
        [E("in", "mod"), E("mod", "cond"), E("cond", "block", "true"), E("cond", "pub", "false")])


def shape_translate_reply(domain, field, sample):
    return (
        f"{domain.title()} · translate & reply",
        f"Translate a {field} to English, then draft a reply.",
        [N("in", "input", "Input", 40, 160, {"sample": {field: sample}}),
         prompt_node("tr", "To English", 300, 160, "Translate the input to English. Output only the translation.",
                     f"{{{{input.{field}}}}}"),
         prompt_node("rep", "Reply", 560, 160, f"You are a {domain} assistant.", "{{tr.text}}"),
         N("out", "output", "Reply", 820, 160, {"value": "{{rep.text}}"})],
        [E("in", "tr"), E("tr", "rep"), E("rep", "out")])


def shape_score_gate(domain, field, sample):
    return (
        f"{domain.title()} · score & gate",
        f"Score a {field} 1-5 for priority, then gate on the number.",
        [N("in", "input", "Input", 40, 200, {"sample": {field: sample}}),
         prompt_node("score", "Score", 300, 200,
                     "Rate priority from 1 (low) to 5 (high). Reply with only the number.",
                     f"{{{{input.{field}}}}}"),
         N("cond", "condition", "> 3?", 560, 200, {"left": "{{score.text}}", "op": ">", "right": "3"}),
         N("hi", "output", "High priority", 820, 110, {"value": "priority {{score.text}}: escalate"}),
         N("lo", "output", "Normal", 820, 300, {"value": "priority {{score.text}}: queue"})],
        [E("in", "score"), E("score", "cond"), E("cond", "hi", "true"), E("cond", "lo", "false")])


def shape_sentiment_route(domain, field, sample):
    return (
        f"{domain.title()} · sentiment route",
        f"Detect sentiment of a {field}, escalate the negative ones.",
        [N("in", "input", "Input", 40, 200, {"sample": {field: sample}}),
         prompt_node("sent", "Sentiment", 300, 200,
                     "Classify sentiment as positive, negative, or neutral. Reply with only that word.",
                     f"{{{{input.{field}}}}}"),
         N("cond", "condition", "Negative?", 560, 200, {"left": "{{sent.text}}", "op": "contains", "right": "negative"}),
         N("esc", "output", "Escalate", 820, 110, {"value": "unhappy customer — escalate"}),
         N("ok", "output", "Thank", 820, 300, {"value": "thanks for the feedback"})],
        [E("in", "sent"), E("sent", "cond"), E("cond", "esc", "true"), E("cond", "ok", "false")])


def shape_draft_critique_revise(domain, field, sample):
    return (
        f"{domain.title()} · draft, critique, revise",
        f"Draft a reply, self-critique it, then produce a revised final.",
        [N("in", "input", "Input", 40, 160, {"sample": {field: sample}}),
         prompt_node("draft", "Draft", 300, 160, f"You are a {domain} assistant.", f"{{{{input.{field}}}}}"),
         prompt_node("crit", "Critique", 560, 160,
                     "List one concrete way to improve this reply. Be brief.", "{{draft.text}}"),
         prompt_node("rev", "Revise", 820, 160,
                     "Rewrite the reply applying the critique. Output only the improved reply.",
                     "Reply: {{draft.text}}\nCritique: {{crit.text}}"),
         N("out", "output", "Final", 1080, 160, {"value": "{{rev.text}}"})],
        [E("in", "draft"), E("draft", "crit"), E("crit", "rev"), E("rev", "out")])


def shape_language_route(domain, field, sample):
    return (
        f"{domain.title()} · language route",
        f"Detect the language of a {field}; answer directly if English, else translate first.",
        [N("in", "input", "Input", 40, 200, {"sample": {field: sample}}),
         prompt_node("lang", "Detect", 300, 200,
                     "Reply with only the language name of the input.", f"{{{{input.{field}}}}}"),
         N("cond", "condition", "English?", 560, 200, {"left": "{{lang.text}}", "op": "contains", "right": "english"}),
         prompt_node("en", "Answer", 820, 110, f"You are a {domain} assistant.", f"{{{{input.{field}}}}}"),
         prompt_node("xl", "Translate & answer", 820, 300,
                     f"Translate to English, then answer as a {domain} assistant.", f"{{{{input.{field}}}}}"),
         N("o1", "output", "Reply (EN)", 1100, 110, {"value": "{{en.text}}"}),
         N("o2", "output", "Reply (translated)", 1100, 300, {"value": "{{xl.text}}"})],
        [E("in", "lang"), E("lang", "cond"),
         E("cond", "en", "true"), E("cond", "xl", "false"), E("en", "o1"), E("xl", "o2")])


def shape_tag_enrich(domain, field, sample):
    return (
        f"{domain.title()} · tag & enrich",
        f"Produce a JSON list of topic tags for a {field}.",
        [N("in", "input", "Input", 40, 160, {"sample": {field: sample}}),
         prompt_node("tag", "Tag", 340, 160,
                     "Return a JSON array of 3 short topic tags for the input. Only the JSON array.",
                     f"{{{{input.{field}}}}}"),
         N("out", "output", "Tags", 640, 160, {"value": "{{tag.text}}"})],
        [E("in", "tag"), E("tag", "out")])


def shape_faq_answer(domain, field, sample):
    return (
        f"{domain.title()} · FAQ match & answer",
        f"Match a {field} to a topic, then answer in that context.",
        [N("in", "input", "Input", 40, 160, {"sample": {field: sample}}),
         prompt_node("topic", "Match topic", 300, 160,
                     "Pick the single best topic: billing, technical, account, other. Only the word.",
                     f"{{{{input.{field}}}}}"),
         prompt_node("ans", "Answer", 560, 160,
                     f"You are a {domain} assistant. Tailor the answer to the matched topic.",
                     "Topic: {{topic.text}}\nQuestion: {{input.%s}}" % field),
         N("out", "output", "Answer", 820, 160, {"value": "{{ans.text}}"})],
        [E("in", "topic"), E("topic", "ans"), E("ans", "out")])


def shape_redact_summarize(domain, field, sample):
    return (
        f"{domain.title()} · redact & summarize",
        f"Redact personal data from a {field}, then summarize the rest.",
        [N("in", "input", "Input", 40, 160, {"sample": {field: sample}}),
         prompt_node("red", "Redact PII", 300, 160,
                     "Replace names, emails, phone numbers, and card numbers with [REDACTED]. "
                     "Output only the redacted text.", f"{{{{input.{field}}}}}"),
         prompt_node("sum", "Summarize", 560, 160, "Summarize in one sentence.", "{{red.text}}"),
         N("out", "output", "Safe summary", 820, 160, {"value": "{{sum.text}}"})],
        [E("in", "red"), E("red", "sum"), E("sum", "out")])


def shape_severity_tiers(domain, field, sample):
    return (
        f"{domain.title()} · severity tiers",
        f"Classify severity of a {field}, then route across three tiers with chained checks.",
        [N("in", "input", "Input", 40, 240, {"sample": {field: sample}}),
         prompt_node("sev", "Severity", 280, 240,
                     "Classify severity as high, medium, or low. Reply with only that word.",
                     f"{{{{input.{field}}}}}"),
         N("c1", "condition", "High?", 540, 240, {"left": "{{sev.text}}", "op": "contains", "right": "high"}),
         N("p1", "output", "Tier 1 (page)", 820, 120, {"value": "P1: page on-call"}),
         N("c2", "condition", "Medium?", 820, 300, {"left": "{{sev.text}}", "op": "contains", "right": "medium"}),
         N("p2", "output", "Tier 2 (queue)", 1080, 240, {"value": "P2: engineer queue"}),
         N("p3", "output", "Tier 3 (backlog)", 1080, 380, {"value": "P3: backlog"})],
        [E("in", "sev"), E("sev", "c1"),
         E("c1", "p1", "true"), E("c1", "c2", "false"),
         E("c2", "p2", "true"), E("c2", "p3", "false")])


def shape_keyword_extract(domain, field, sample):
    return (
        f"{domain.title()} · keyword extract",
        f"Pull the top keywords from a {field} as a JSON array.",
        [N("in", "input", "Input", 40, 160, {"sample": {field: sample}}),
         prompt_node("kw", "Keywords", 340, 160,
                     "Return a JSON array of the 5 most important keywords. Only the JSON array.",
                     f"{{{{input.{field}}}}}"),
         N("out", "output", "Keywords", 640, 160, {"value": "{{kw.text}}"})],
        [E("in", "kw"), E("kw", "out")])


def shape_tone_rewrite(domain, field, sample):
    return (
        f"{domain.title()} · tone rewrite",
        f"Rewrite a {field} in a warm, professional tone.",
        [N("in", "input", "Input", 40, 160, {"sample": {field: sample}}),
         prompt_node("rw", "Rewrite", 340, 160,
                     "Rewrite the input in a warm, professional tone. Output only the rewrite.",
                     f"{{{{input.{field}}}}}"),
         N("out", "output", "Rewritten", 640, 160, {"value": "{{rw.text}}"})],
        [E("in", "rw"), E("rw", "out")])


def shape_action_items(domain, field, sample):
    return (
        f"{domain.title()} · action items",
        f"Turn a {field} into a JSON list of action items.",
        [N("in", "input", "Input", 40, 160, {"sample": {field: sample}}),
         prompt_node("ai", "Extract actions", 340, 160,
                     "List concrete action items as a JSON array of short strings. Only the JSON array.",
                     f"{{{{input.{field}}}}}"),
         N("out", "output", "Action items", 640, 160, {"value": "{{ai.text}}"})],
        [E("in", "ai"), E("ai", "out")])


SHAPES = [shape_answer, shape_classify_route, shape_extract_validate, shape_classify_label,
          shape_summarize_then_act, shape_moderate_gate, shape_translate_reply,
          shape_score_gate, shape_sentiment_route, shape_draft_critique_revise,
          shape_language_route, shape_tag_enrich, shape_faq_answer,
          shape_redact_summarize, shape_severity_tiers, shape_keyword_extract,
          shape_tone_rewrite, shape_action_items]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for f in OUT.glob("*.yaml"):
        f.unlink()
    written, seen = 0, set()
    index = []
    for shape in SHAPES:
        for domain, field, sample in DOMAINS:
            name, desc, nodes, edges = shape(domain, field, sample)
            fn = slug(name)
            if fn in seen:
                continue
            seen.add(fn)
            text = testfile.dump_flow(name, desc, nodes, edges)
            testfile.load(text)  # validate every generated flow
            (OUT / f"{fn}.yaml").write_text(text)
            index.append((name, desc))
            written += 1
    _write_index(index)
    print(f"wrote {written} demo flows to {OUT}")


def _write_index(index):
    lines = ["# Demo flow gallery",
             "",
             f"{len(index)} ready-to-import example flows. Each references the keyless "
             "**Demo Assistant (mock)** connection, so they run offline out of the box. "
             "Import via the app (Flows → import) or `POST /api/import`, then hit Run.",
             "", "| Flow | What it does |", "|---|---|"]
    for name, desc in sorted(index):
        lines.append(f"| `{slug(name)}.yaml` | {desc} |")
    (OUT / "README.md").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
