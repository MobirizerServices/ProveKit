"""SCIM 2.0 endpoints (`/scim/v2`) — the HTTP shell over services/scim.py (#78).

Deliberately thin: every decision that matters (what a bearer token is allowed to reach, what
`active: false` actually revokes, how a role maps to a group) lives in the service, where it
is testable without a client. What lives here is the parts that are genuinely HTTP — SCIM's
error envelope, its `application/scim+json` media type, and 1-based paging parameters.

**Authentication is a tenant SCIM token, not a project key.** See services/scim.authenticate:
it never touches `workspace_from_key`, so a `pk_` key that leaks out of CI cannot delete
anyone. The token is configured per tenant in `PROVEKIT_SCIM_TOKENS`.

Not registered in main.py by this change — see docs/SCIM.md for the one line that turns it on.
"""
from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from sqlalchemy.orm import Session

from ..database import get_db
from ..services import roles, scim


class ScimJSON(JSONResponse):
    """SCIM responses are `application/scim+json` (RFC 7644 §3.1). Some connectors check it."""
    media_type = scim.MEDIA_TYPE


def error_response(exc: Exception) -> ScimJSON:
    """A rejection as a SCIM Error resource.

    A separate function, not an inline `except` block, so it can be tested without a live
    route: this is the piece a connector's admin actually reads when a sync fails.
    """
    if isinstance(exc, scim.ScimError):
        return ScimJSON(status_code=exc.status_code,
                        content=scim.error_body(exc.status_code, str(exc.detail), exc.scim_type))
    if isinstance(exc, HTTPException):
        return ScimJSON(status_code=exc.status_code,
                        content=scim.error_body(exc.status_code, str(exc.detail)))
    return ScimJSON(status_code=400,
                    content=scim.error_body(400, "Body is not a SCIM JSON object.", "invalidSyntax"))


class _ScimRoute(APIRoute):
    """Turn every rejection into a SCIM Error resource.

    Without this the 401 from the auth dependency comes back as FastAPI's `{"detail": …}`,
    which a connector logs as an unparseable response and shows its admin as a generic
    failure. Done as a route class rather than an app-level exception handler so it is
    self-contained: registering the router is the only wiring this feature needs.
    """

    def get_route_handler(self):
        original = super().get_route_handler()

        async def wrapped(request: Request) -> Response:
            try:
                return await original(request)
            except (HTTPException, RequestValidationError) as exc:
                return error_response(exc)

        return wrapped


router = APIRouter(prefix=scim.BASE_PATH, tags=["scim"], route_class=_ScimRoute,
                   default_response_class=ScimJSON)


def require_scim(request: Request, db: Session = Depends(get_db)) -> scim.ScimContext:
    return scim.authenticate(db, request.headers.get("authorization"))


@router.get("/ServiceProviderConfig")
def service_provider_config(ctx: scim.ScimContext = Depends(require_scim)):
    """What this implementation really supports. Advertising nothing we haven't built is the
    point: a connector that believes `bulk` or `sort` works fails later and less clearly."""
    return {"schemas": ["urn:ietf:params:scim:schemas:core:2.0:ServiceProviderConfig"],
            "patch": {"supported": True},
            "bulk": {"supported": False, "maxOperations": 0, "maxPayloadSize": 0},
            "filter": {"supported": True, "maxResults": scim.MAX_COUNT},
            "changePassword": {"supported": False},
            "sort": {"supported": False},
            "etag": {"supported": False},
            "authenticationSchemes": [{"type": "oauthbearertoken", "name": "Bearer token",
                                       "description": "Tenant SCIM token (PROVEKIT_SCIM_TOKENS), "
                                                      "not a project API key."}]}


# ---- Users ----
@router.get("/Users")
def list_users(filter: str = Query("", alias="filter"), startIndex: int = 1,
               count: int = scim.DEFAULT_COUNT,
               ctx: scim.ScimContext = Depends(require_scim), db: Session = Depends(get_db)):
    rows = scim.apply_filter(scim.visible(db, ctx.workspace_id), filter)
    window = scim.page(rows, start_index=startIndex, count=count)
    return scim.list_response(
        [scim.user_resource(u, workspace_id=ctx.workspace_id, role=r) for u, r in window],
        total=len(rows), start=max(1, startIndex))


@router.get("/Users/{user_id}")
def get_user(user_id: str, ctx: scim.ScimContext = Depends(require_scim),
             db: Session = Depends(get_db)):
    user, role = scim.find(db, ctx, user_id)
    return scim.user_resource(user, workspace_id=ctx.workspace_id, role=role)


@router.post("/Users", status_code=201)
def create_user(request: Request, body: dict = Body(default_factory=dict),
                ctx: scim.ScimContext = Depends(require_scim), db: Session = Depends(get_db)):
    user, role = scim.create(
        db, ctx, user_name=str(body.get("userName") or ""),
        display_name=str(body.get("displayName") or (body.get("name") or {}).get("formatted") or ""),
        active=body.get("active", True) is not False, request=request)
    return ScimJSON(status_code=201,
                    content=scim.user_resource(user, workspace_id=ctx.workspace_id, role=role))


@router.put("/Users/{user_id}")
def replace_user(user_id: str, request: Request, body: dict = Body(default_factory=dict),
                 ctx: scim.ScimContext = Depends(require_scim), db: Session = Depends(get_db)):
    user, _ = scim.find(db, ctx, user_id)
    role = scim.apply_replace(db, ctx, user, body, request=request)
    return scim.user_resource(user, workspace_id=ctx.workspace_id, role=role)


@router.patch("/Users/{user_id}")
def patch_user(user_id: str, request: Request, body: dict = Body(default_factory=dict),
               ctx: scim.ScimContext = Depends(require_scim), db: Session = Depends(get_db)):
    """The deprovisioning call: `{"op":"replace","path":"active","value":false}`."""
    user, _ = scim.find(db, ctx, user_id)
    role = scim.apply_patch(db, ctx, user, body.get("Operations") or [], request=request)
    return scim.user_resource(user, workspace_id=ctx.workspace_id, role=role)


@router.delete("/Users/{user_id}", status_code=204)
def delete_user(user_id: str, request: Request, ctx: scim.ScimContext = Depends(require_scim),
                db: Session = Depends(get_db)):
    """Same revocation as `active: false`, and the account also stops being visible here."""
    user, _ = scim.find(db, ctx, user_id)
    scim.deactivate(db, ctx, user, forget=True, request=request)
    return Response(status_code=204)


# ---- Groups (the three project roles) ----
@router.get("/Groups")
def list_groups(ctx: scim.ScimContext = Depends(require_scim), db: Session = Depends(get_db)):
    groups = [scim.group_resource(db, ctx, role) for role in sorted(roles.ALL_ROLES)]
    return scim.list_response(groups, total=len(groups), start=1)


@router.get("/Groups/{group_id}")
def get_group(group_id: str, ctx: scim.ScimContext = Depends(require_scim),
              db: Session = Depends(get_db)):
    return scim.group_resource(db, ctx, scim.parse_group_id(ctx, group_id))


@router.patch("/Groups/{group_id}")
def patch_group(group_id: str, request: Request, body: dict = Body(default_factory=dict),
                ctx: scim.ScimContext = Depends(require_scim), db: Session = Depends(get_db)):
    role = scim.parse_group_id(ctx, group_id)
    scim.patch_group(db, ctx, role, body.get("Operations") or [], request=request)
    return scim.group_resource(db, ctx, role)
