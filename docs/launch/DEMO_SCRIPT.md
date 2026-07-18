# 90-second demo script (the thing that decides the launch)

The demo matters more than any copy. Record ONE take that shows the loop: point at an
agent → run it → turn the run into a test → run the suite in a terminal. No narration
needed (most people watch muted); on-screen captions carry it. Keep it under 90s.

## Before you record (setup)

- `make backend` + `make frontend`, browser at localhost:3001, window ~1280×800.
- **Zoom the browser to 110–125%** so text is legible in the GIF/video.
- Pre-open a terminal beside or below the browser for the CLI beat.
- Have the seeded **Demo Assistant (mock)** connection present (it is, on first run) so the
  whole demo runs offline with zero keys — no waiting on a real API, no secrets on screen.
- Do a dry run once so the mouse path is smooth. Hesitation reads as "clunky."
- Tool: Kap or CleanShot (Mac) → export GIF *and* MP4. GIF for the README, MP4/Loom for the
  post (HN allows a link; some people prefer video).

## The shot list (target times are cumulative)

**0:00–0:08 — The hook: it's already running.**
- Open on the Console with the demo agent selected. Caption: **"Point ProveKit at any agent
  — no SDK."**
- Click **Run**. Tokens stream in live. Let the stream finish visibly.

**0:08–0:20 — Turn the run into a test (the money shot).**
- On the response, click **+ contains**. An assertion appears in the editor.
- Click **Run** again. The assertion panel shows **✓ passed**. Caption: **"Turn any run into
  a regression test — one click."**
- (Optional micro-beat: click a field in the JSON output → **+ assert** to show json_path.)

**0:20–0:35 — It's a real protocol client, not just LLM calls.**
- Switch the request type tab to **Tool (MCP)** (or **A2A**). Show the tool list auto-
  discovered from a connected MCP server, pick one, run it, structured JSON comes back.
  Caption: **"MCP servers, HTTP agents, A2A — same client."**
- (If you don't have a live MCP server handy, skip to the flow beat — don't fake it.)

**0:35–0:55 — Build + deploy a flow.**
- Go to **Flows**, open the seeded demo flow. Click **Run** — nodes light up left to right
  with timings. Caption: **"Chain steps into a flow, step-debug it."**
- Click **▲ Deploy**. The modal shows the endpoint URL + a one-time key + a ready curl.
  Caption: **"…then ship it as a hosted API."**

**0:55–1:20 — The CI beat (this is what makes devs trust it).**
- Cut to the terminal. Run:
  ```
  provekit run .provekit/tests/
  ```
- Show the green output: `✓ passed`, and the `1/1 passed` / exit 0 line. Caption: **"Run the
  same tests headless in CI. Plain-text .provekit files, no secrets."**

**1:20–1:30 — Close.**
- Cut back to the Console. Caption: **"Open source · local-first · runs offline.
  github.com/…"**
- End on the repo URL held for 2 seconds so a pause-frame gives the link.

## Caption style

- Short, lowercase-friendly, one line, high-contrast (white text, subtle dark pill).
- Verbs, not features: "turn any run into a test," not "assertion engine."
- Never more than ~7 words on screen at once.

## Do / don't

- **Do** keep the mouse moving with intent; **do** let each result fully render before moving.
- **Do** make the first 8 seconds land — most people bail before 0:10. Lead with the stream.
- **Don't** show a login (record in local mode), real API keys, or a loading spinner you
  waited on. **Don't** narrate obvious clicks. **Don't** exceed 90s — cut the MCP beat first
  if you must.

## Two shorter cuts to also export

- **~15s loop for the README top** (autoplaying GIF): just the 0:00–0:20 beat — run → +assert
  → ✓ passed. That single loop is the whole value prop and is what most repo visitors see.
- **~30s for Twitter/X** (video autoplays there): 0:00–0:20 + the CLI beat (0:55–1:20).
