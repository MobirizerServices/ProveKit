"""Rejection messages that name the fix (#34).

Every 4xx a user meets is a dead end unless the text says what to *do*. "Invalid ingest key"
is a symptom; "the key is revoked or belongs to another project — mint a fresh one in
Settings → API keys" is an instruction. The rule this module exists to enforce: a competent
user who has never read the source must be able to act on the message alone.

The phrasing lives here rather than as literals in the routers for two reasons:

1. The same condition is rejected from several places (a stale connection id, a cross-project
   404). Scattered literals drift, and two wordings for one cause read to a user as two
   different problems.
2. A docs link needs one convention — one base URL, one place in the sentence, one bit of
   punctuation. `with_docs` is that convention; hand-written links in a dozen f-strings are
   how you end up with three of them.

Status codes and response shapes are NOT this module's business: it returns strings that go
into the `detail` of an HTTPException the caller already decided on. Clients and tests depend
on those codes.

Not yet covered: the ingest path. "Invalid ingest key" is raised by `services/workspace.py`
and the OTLP/backpressure rejections by `routers/traces.py` — both outside this change's
ownership, so they still read as symptoms. They belong here when someone owns those files.
"""
from __future__ import annotations

# Docs are read on GitHub (there is no docs site yet); `blob/main` is the form that renders
# rather than downloads, and it survives a checkout at any tag.
DOCS_BASE = "https://github.com/MobirizerServices/ProveKit/blob/main/docs"


def with_docs(message: str, page: str, anchor: str = "") -> str:
    """`message` plus a trailing pointer to a docs page — the only place links are formatted.

    Trailing on purpose: the fix has to be readable in a toast that truncates, and a URL in
    the middle of a sentence is the part that survives while the instruction is cut off.
    """
    url = f"{DOCS_BASE}/{page}" + (f"#{anchor}" if anchor else "")
    return f"{message} See {url}"


_DEBUG_DOC = "DEBUGGING.md"
_REJECTIONS = "rejections-and-what-to-do-about-them"


# --------------------------------------------------------------------- accounts / sessions
EMAIL_TAKEN = ("An account with that email already exists. Sign in instead, or use the "
               "\"Forgot password\" link on the sign-in page to get back into it.")

WEAK_PASSWORD = "Password must be at least 8 characters"

# Deliberately does not say *which* half was wrong — telling an anonymous caller that an email
# exists is account enumeration. Saying so out loud is better than looking evasive: the user
# stops hunting for a distinction the API will never draw and moves to the reset flow.
BAD_CREDENTIALS = ("Email or password is incorrect. Try again, or reset your password from "
                   "\"Forgot password\" — for your safety we don't say which of the two was wrong, "
                   "because that would reveal whether an account exists.")

# The recovery route named here is real: /api/auth/reset sets email_verified on success, so a
# password reset is the way out of an expired verification link. There is no resend endpoint,
# so do not promise one.
EMAIL_UNVERIFIED = ("This account's email isn't verified yet. Open the verification link sent when "
                    "you signed up (valid 48 hours); if it has expired, use \"Forgot password\" — "
                    "completing a reset verifies the address too.")

RESET_LINK_DEAD = ("This password-reset link is no longer valid. Reset links last one hour and work "
                   "once, and requesting a new one or changing your password cancels older links — "
                   "request a fresh one from \"Forgot password\".")

VERIFY_LINK_DEAD = ("This verification link is no longer valid. Verification links last 48 hours and "
                    "are cancelled by a password reset — use \"Forgot password\" to set a password, "
                    "which verifies your email at the same time.")


# --------------------------------------------------------------------- tenancy / membership
#
# Cross-project access is answered with 404, not 403, so that a caller can't enumerate other
# tenants' ids. That is the right call and it is also exactly why the text must explain itself:
# without this sentence, a user staring at a project they can see in another tab has no way to
# guess that the X-Project-Id header is the problem.
def not_in_project(thing: str, listing: str) -> str:
    """404 text for a row that exists in some other project (or not at all).

    `thing` names the row ("API key"), `listing` the call that enumerates the ones you can see.
    """
    return (f"No {thing} with that id in the current project. {listing} lists what's here — and check "
            f"the X-Project-Id header, because a {thing} belonging to another project is reported as "
            f"missing rather than forbidden, so ids can't be probed across tenants.")


PROJECT_NOT_FOUND = ("No project with that id that you're a member of. Check the id against "
                     "GET /api/projects; if a teammate owns it, ask them to add you — a project you "
                     "aren't a member of is reported as missing rather than forbidden.")

OWNER_ONLY = ("Only a project owner can change project settings or membership. "
              "GET /api/projects/{pid}/members lists the owners — ask one of them to make the change, "
              "or to give you the owner role.")

NO_SUCH_ACCOUNT = ("No ProveKit account uses that email. Members are added to a project by account, not "
                   "invited by email, so ask them to sign up with this exact address first — then add "
                   "them again.")

# There is no role-change endpoint on this router, so "remove and re-add" is the honest fix
# rather than a pointer to a PATCH that doesn't exist.
ALREADY_MEMBER = ("That account is already a member of this project. To change their access, remove "
                  "them and add them again with the role you want.")

NOT_A_MEMBER = ("That user isn't a member of this project, so there's nothing to remove. "
                "GET /api/projects/{pid}/members lists the current members and their user ids.")

LAST_OWNER = ("This is the project's only owner — removing them would leave nobody able to manage "
              "members, keys or settings. Add another member as an owner first, then remove this one.")

# The viewer-write refusal is phrased in services/workspace._guard_viewer and already names its
# fix; it is deliberately not duplicated here, because two copies of one sentence is the drift
# this module exists to prevent.


# --------------------------------------------------------------------- alerts
def bad_alert_metric(got: str, allowed) -> str:
    return (f"'{got}' isn't a metric an alert can watch. Use one of: {', '.join(sorted(allowed))} "
            "— these are the numeric fields of the dashboard metrics an alert is evaluated against.")


def bad_comparator(got: str) -> str:
    return (f"comparator must be 'gt' (fire when the metric rises above the threshold) or 'lt' (fire "
            f"when it falls below); got '{got}'.")


def bad_webhook(reason: str) -> str:
    """A webhook URL refused by netguard. The reason alone doesn't tell anyone what would pass."""
    return (f"webhook_url was rejected: {reason}. Give a public https:// URL this server can reach — "
            "localhost, private-range and link-local addresses are refused so an alert can't be aimed "
            "at internal infrastructure. Leave the field empty to alert by email only.")


# --------------------------------------------------------------------- playground / replay
def bad_provider(got: str, allowed) -> str:
    return with_docs(
        f"'{got}' isn't a supported provider. Use one of: {', '.join(sorted(allowed))}.",
        _DEBUG_DOC, "1-add-a-model-connection-one-time")


def provider_key_required(provider: str) -> str:
    return with_docs(
        f"A provider API key is required for '{provider}': ProveKit calls the provider with your own "
        "credentials and never ships one of its own. Add the key on a model connection first.",
        _DEBUG_DOC, "1-add-a-model-connection-one-time")


BASE_URL_REQUIRED = with_docs(
    "An OpenAI-compatible connection needs base_url — the root of the provider's API "
    "(e.g. https://openrouter.ai/api/v1 or http://localhost:11434/v1), without the "
    "/chat/completions suffix, which ProveKit appends.",
    _DEBUG_DOC, "1-add-a-model-connection-one-time")

NO_MODEL_CHOSEN = with_docs(
    "This run has no model to call. Pass connection_id from GET /api/connections — add a model "
    "connection with your provider key first if you have none.",
    _DEBUG_DOC, "1-add-a-model-connection-one-time")

NO_MESSAGES = ("A run needs at least one message: send messages as "
               "[{\"role\": \"user\", \"content\": \"…\"}]. An empty list has nothing to send to the model.")


NO_EDITS = ("A replay needs at least one edit — a span to change and what to change it to. Replaying a "
            "trace with nothing changed would just re-run it into an identical branch.")


def span_no_messages(span_id: str) -> str:
    return (f"The edit for span {span_id} has no messages. An llm edit replaces the captured prompt, so "
            "it must carry the full message list to send — use kind='tool' if you meant to edit a tool "
            "call's arguments instead.")


def too_many_edits(sent: int, cap: int) -> str:
    return (f"A replay can edit at most {cap} spans at once, and this request has {sent}. Each llm edit "
            "makes a live provider call, so the cap bounds what one request can spend — drop the edits "
            "that don't affect the output you're testing.")


EDIT_NEEDS_SPAN_ID = ("Every edit needs the span_id of the captured span it replaces. Copy it from the "
                      "trace view, or from GET /api/traces/{trace_id}.")


def duplicate_edit(span_id: str) -> str:
    return (f"Span {span_id} appears in two edits. There's no defined order between them, so one would be "
            "silently dropped — merge them into a single edit for that span.")


def bad_edit_kind(got: str) -> str:
    return (f"edit kind must be 'llm' (replace the prompt and re-run the call) or 'tool' (replace the "
            f"recorded tool arguments — ProveKit doesn't execute your tools); got '{got}'.")


def tool_edit_needs_arguments(span_id: str) -> str:
    return (f"The tool edit for span {span_id} has no `arguments`. Supply the replacement input for the "
            "captured tool call (a JSON object, array or string) — nothing is executed; identical "
            "arguments serve the recorded response and changed ones mark it diverged.")


PROMPT_NAME_REQUIRED = ("A saved prompt needs a name — it's the key versions are grouped under, so saving "
                        "again under the same name creates version 2 rather than overwriting version 1.")


def dataset_unusable(dataset_id: int) -> str:
    return with_docs(
        f"Dataset {dataset_id} has no items in this project — it's either empty or belongs to another "
        "project. Check the id against GET /api/datasets and add at least one input/expected item; there "
        "is nothing to score an edit against otherwise.",
        _DEBUG_DOC, "4-evaluate-an-edit-over-a-dataset")


def provider_failed(reason: str) -> str:
    """502: the upstream model provider refused or broke. `reason` is the provider's own words,
    kept verbatim — it is usually the most specific thing anyone will get about the failure.

    Says nothing about what was or wasn't saved: the same wording covers a single re-run (which
    stores nothing) and a dataset evaluation (which keeps the items it scored before the break).
    """
    return with_docs(
        f"The model provider rejected this call: {reason}. Check the model name and the connection's API "
        "key in Settings → Model connections; if the provider is rate-limiting or down, retry shortly.",
        _DEBUG_DOC, _REJECTIONS)


# What a replay can't find. Keyed on the reasons services/replay.py raises: a reason we don't
# recognise passes through untouched rather than acquiring advice that might be wrong for it
# (the webhook-not-configured case, for one, already names its own fix).
_REPLAY_HINTS = {
    "origin trace not found": ("Check origin_trace_id against GET /api/traces, and the X-Project-Id "
                               "header — a trace in another project isn't visible here."),
    "fork span not in trace": ("A replay can only fork a span belonging to the trace it names — take "
                               "fork_span_id from GET /api/traces/{origin_trace_id}."),
}


def replay_target_missing(reason: str) -> str:
    hint = _REPLAY_HINTS.get(reason.strip().lower())
    if not hint:
        return reason
    return with_docs(f"Replay failed: {reason}. {hint}",
                     _DEBUG_DOC, "3-replay-flow--re-run-the-whole-trace-from-a-step")

def dataset_version_missing(dataset_id: int, version: int, retained: int) -> str:
    """404 for a version whose contents were never captured or have since been pruned.

    Names both causes, because "we never had it" and "we dropped it" call for different next
    steps and the caller cannot tell them apart from the status code.
    """
    return with_docs(
        f"No stored contents for dataset {dataset_id} v{version}. Snapshots start at a dataset's "
        f"first change, and only the newest {retained} versions are kept — so this version either "
        f"predates snapshots or has been pruned. Use GET /api/datasets/{dataset_id}/versions to "
        "see which versions are still retrievable.",
        "EVALUATION.md")
