"""Project roles, and the read-only viewer.

Membership was owner-or-member and both could write. That is the wrong default for most of
the people who need access: the stakeholders who want to look at traces — a PM, a support
lead, someone on another team — had to be given a role that can delete a project's data, so
in practice they either got too much or got nothing.

`viewer` is that missing role. Enforcement lives in `workspace.current_workspace`, immediately
after the workspace is resolved — deliberately NOT in a middleware, which is what I built
first and which was wrong.

A middleware can only read `X-Project-Id`, but that header is a *request*, not an answer:
`current_workspace` honours it only for projects you belong to and otherwise falls back to
your default project. So the middleware authorized one project while the write landed in
another, and a viewer could bypass it entirely by pointing the header at a project they were
not a member of. One resolution and one authorization decision, in one place, is the only
arrangement where those cannot disagree.

It stays method-based rather than a list of protected routes: a mutating endpoint written next
month is covered the day it is written, and nobody has to remember to add it.
"""
from __future__ import annotations

from starlette.responses import JSONResponse

OWNER = "owner"
MEMBER = "member"
VIEWER = "viewer"

#: Roles that may change anything in a project.
WRITE_ROLES = {OWNER, MEMBER}
ALL_ROLES = {OWNER, MEMBER, VIEWER}

_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

#: Only project-scoped API routes are guarded. Auth routes must stay writable — a viewer still
#: has to be able to log in, log out and reset their own password, none of which is a change to
#: the project's data.
_GUARDED_PREFIXES = ("/api/traces", "/api/runs", "/api/datasets", "/api/experiments",
                     "/api/alerts", "/api/views", "/api/playground", "/api/workspace",
                     "/api/metrics", "/api/projects")
_UNGUARDED = ("/api/projects/switch",)   # choosing which project to look at is not a write


def can_write(role: str | None) -> bool:
    return (role or "") in WRITE_ROLES
