# Customer discovery — agent-debugging interview

> Purpose: test the one question our competitive research could not answer — **do developers
> who build LLM agents actually want to pause a run mid-execution and inspect/edit state, or
> are they satisfied with post-hoc traces (LangSmith / Langfuse / AgentOps)?**
>
> Context: four deep-research passes established that (a) LangGraph already owns first-party
> live step-debugging, (b) the entire third-party market is post-hoc tracing — nobody ships
> live pause/inspect/edit/resume, and (c) "framework-agnostic" is really N bespoke
> integrations (only LlamaIndex Workflows, smolagents, and Haystack expose a hookable
> mid-run substrate). See `PRODUCT_STRATEGY.md`. The remaining unknown is **demand**, and
> that is a customer question, not a research question. This script answers it.

## For your eyes only — do not say any of this aloud

**Hypothesis under test:** developers building LLM agents have an unmet need to pause a run
mid-execution and inspect/edit state, beyond what post-hoc traces give them.

**The decision this feeds:** GO (build the live stepper) if people are already hacking around
the lack of it; PIVOT / KILL if trace-replay is "good enough."

**Cardinal rules (The Mom Test):**
1. **Never mention the idea, "step-debugger", "breakpoints", or "pause"** until the reveal at
   the end. The moment you pitch, people turn polite and the data dies.
2. **Ask about the past, never the future.** "Tell me about the last time…", not "Would you…".
3. **Dig into specifics.** When they say "it was a pain", ask "walk me through exactly what
   you did."
4. **You want to hear "no" / "I don't have that problem."** A cheap invalidation now is worth
   months.
5. **Talk 20%, listen 80%.** Silence after their answer usually earns you the real answer.

## Who to talk to (8–10 people)

Developers who have **shipped or seriously built** an LLM agent — not people who have only
read about them. Find them in: LangGraph / CrewAI / LlamaIndex Discords, r/LLMDevs, the
"who's building agents" threads on X / HN, your own network. Skip weekend toys — you want
people who have felt real pain. 20–30 min each.

---

## The script

### Warm-up (2 min) — their world, not yours
1. What are you building with agents right now?
2. What framework / stack — and how did you land on it? *(validates the target-framework list)*
3. How far along is it — prototype, in prod, somewhere between?

### The core story (10 min) — this is 80% of the value
4. Think about the **last time your agent did something wrong or weird**. What happened?
5. Walk me through **exactly** what you did next — step by step, what you ran, what you
   clicked. *(Then shut up. Listen for: print statements, re-running with tweaks, staring at
   a trace, adding logging, bisecting the prompt.)*
6. How long did that take you to figure out?
7. What made it hard? Where did you get stuck?
8. How often does that kind of thing happen — daily, weekly?

### Current tools & their edges (5 min) — still not pitching
9. What tools are you using to see what your agent is doing? *(LangSmith? Langfuse? print?
   nothing?)*
10. When you're looking at [their tool], what are you actually trying to answer?
11. Is there a moment where it **doesn't** show you what you need — where you're guessing, or
    reconstructing what happened in your head? *(Closest to the hypothesis without leading.
    Light-up here = signal. "No, the trace tells me everything" = invalidation.)*
12. Have you ever gone looking for a better tool for this? Paid for one? What made you stop
    looking / what fell short? *(Searching and paying are the strongest buy signals there are.)*

### Only if the loop involves people (optional)
13. Do you ever need a human to step in mid-run — approve something, correct the agent? How
    do you handle that today?

---

## The reveal — last 3–5 minutes only, and only after the truth is out

Now, and only now, show the concept: *"I've been playing with a tool that lets you pause an
agent mid-run — stop it at a step, see the exact state and prompt, tweak it, and continue.
Not a trace after the fact — actually pausing it live."*

Then read the reaction with these (the answers matter more than the enthusiasm):
- **When in the last month would you have reached for that?** *(Vague = polite interest. A
  specific recent incident = real.)*
- **What would you expect it to do that your traces don't?**
- **What are you using today that this would replace?**
- The commitment ask — the real test of interest: **"Can I show you a prototype in two
  weeks?"** or **"Would you pair for 30 min and try it on your actual agent?"** *(A yes with a
  calendar slot = signal. "Sure, send me a link" = a polite no.)*

---

## Decoding the answers

**Real demand (→ GO):**
- Unprompted, they describe **already hacking around it** — print statements to see
  intermediate state, re-running with edited inputs to reproduce, wishing they could "just
  stop it here."
- They have **searched for or paid for** a debugging tool.
- At the reveal, they name a **specific recent incident** and give you a calendar slot.

**Polite interest (→ treat as a NO):**
- "Yeah, that sounds useful / cool / I'd probably use that." (Compliments are not data.)
- Enthusiasm with no past incident behind it.
- "Send me a link when it's ready."

**Genuine invalidation (→ PIVOT or KILL, and be glad you learned it in 3 days):**
- "Honestly the trace tells me everything I need."
- Their debugging story is short and painless.
- They can't remember the last time an agent seriously misbehaved.

## The decision rule

Tally across ~10 interviews. **If ≥4–5 describe pre-existing workarounds AND can point to a
recent incident, the need is real** — proceed to the technical spike on the hookable
frameworks (smolagents `step()` / LlamaIndex `Context`). **If most are satisfied with
traces**, the empty seat is empty for a reason — you've saved months.

Two things to watch as your own advisor:
- **Note which framework each person names.** It doubles as validation of the target list. If
  nobody uses the hookable ones (LlamaIndex / smolagents) and everyone's on the black-box
  Vercel AI SDK, that's the exact problem the research warned about — better learned from real
  people than from a build.
- **The "send me a link" trap is the whole game.** Almost everyone will be nice to you. The
  only answers that count are past behavior and a booked calendar slot. Ten positive-feeling
  calls with zero follow-ups booked is a no, however good the calls felt.

---

## Interview log

Capture verbatim quotes — paraphrase loses the signal. One block per interview.

| # | Framework | In prod? | Current tool | Last-incident story (verbatim) | Showed a workaround? | Searched/paid before? | Booked follow-up? | Verdict |
|---|-----------|----------|--------------|--------------------------------|----------------------|-----------------------|-------------------|---------|
| 1 | | | | | | | | |
| 2 | | | | | | | | |
| 3 | | | | | | | | |
| 4 | | | | | | | | |
| 5 | | | | | | | | |
| 6 | | | | | | | | |
| 7 | | | | | | | | |
| 8 | | | | | | | | |
| 9 | | | | | | | | |
| 10 | | | | | | | | |

**Tally:** ___ / 10 described a pre-existing workaround + recent incident.
**Frameworks named:** ______________________________________________
**Decision:** GO to spike · PIVOT · KILL — because ____________________
