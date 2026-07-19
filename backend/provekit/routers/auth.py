"""Auth endpoints: register / login / logout / me (email + password).

Sessions are httpOnly cookies carrying a signed token. GitHub OAuth is a planned
provider; the User model + session layer are provider-agnostic so it slots in later.
"""
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import get_db
from ..models import User
from ..services import auth, email
from ..services.limits import check_login_rate

router = APIRouter(prefix="/api/auth", tags=["auth"])


class Credentials(BaseModel):
    email: EmailStr
    password: str
    name: str = ""


def _set_cookie(resp: Response, u: User) -> None:
    token = auth.make_token(u.id, ver=u.token_version)
    resp.set_cookie(auth.COOKIE, token, max_age=auth._TTL, httponly=True,
                    samesite="lax", secure=get_settings().hosted, path="/")


def _public(u: User) -> dict:
    from ..config import get_settings
    is_super = u.is_superuser or u.email.lower() in get_settings().superuser_email_list
    return {"id": u.id, "email": u.email, "name": u.name, "auth_provider": u.auth_provider,
            "email_verified": u.email_verified, "is_superuser": is_super}


def _send_verify(u: User) -> None:
    s = get_settings()
    token = auth.make_token(u.id, ttl=2 * 24 * 3600, purpose="verify", ver=u.token_version)
    link = f"{s.web_base_url.rstrip('/')}/verify?token={token}"
    email.send(u.email, "Verify your ProveKit email",
               f"Confirm your email to finish setting up ProveKit:\n\n{link}\n\nThis link expires in 48 hours.")


@router.post("/register")
def register(body: Credentials, response: Response, db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == body.email).first():
        raise HTTPException(409, "An account with that email already exists")
    if len(body.password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters")
    u = User(email=body.email, name=body.name or body.email.split("@")[0],
             password_hash=auth.hash_password(body.password))
    db.add(u); db.commit(); db.refresh(u)
    _send_verify(u)
    if not get_settings().require_email_verification:
        _set_cookie(response, u)  # verification optional → log in immediately
    return _public(u)


@router.post("/login")
def login(body: Credentials, request: Request, response: Response, db: Session = Depends(get_db)):
    client = request.client.host if request.client else "?"
    check_login_rate(f"{body.email}:{client}")  # brute-force throttle
    u = db.query(User).filter(User.email == body.email).first()
    if not u or not u.password_hash:
        # Spend the same PBKDF2 cost on a missing/OAuth account so response time doesn't
        # reveal whether the email exists (timing-based account enumeration).
        auth.verify_password(body.password, auth.DUMMY_HASH)
        raise HTTPException(401, "Invalid email or password")
    if not auth.verify_password(body.password, u.password_hash):
        raise HTTPException(401, "Invalid email or password")
    if get_settings().require_email_verification and not u.email_verified:
        raise HTTPException(403, "Please verify your email before signing in.")
    _set_cookie(response, u)
    return _public(u)


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(auth.COOKIE, path="/")
    return {"ok": True}


@router.get("/me")
def me(user: User = Depends(auth.get_current_user)):
    return _public(user)


class Email(BaseModel):
    email: EmailStr


@router.post("/forgot")
def forgot(body: Email, request: Request, db: Session = Depends(get_db)):
    """Email a password-reset link. Always returns ok — never leaks whether the email exists."""
    client = request.client.host if request.client else "?"
    check_login_rate(f"forgot:{body.email}:{client}")
    u = db.query(User).filter(User.email == body.email).first()
    if u and u.password_hash:
        token = auth.make_token(u.id, ttl=3600, purpose="reset", ver=u.token_version)
        link = f"{get_settings().web_base_url.rstrip('/')}/reset?token={token}"
        email.send(u.email, "Reset your ProveKit password",
                   f"Reset your password with this link (valid 1 hour):\n\n{link}\n\n"
                   "If you didn't request this, ignore this email.")
    return {"ok": True}


class ResetIn(BaseModel):
    token: str
    password: str


@router.post("/reset")
def reset(body: ResetIn, db: Session = Depends(get_db)):
    claims = auth.read_token(body.token, purpose="reset")
    if claims is None:
        raise HTTPException(400, "This reset link is invalid or has expired.")
    if len(body.password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters")
    uid, ver = claims
    u = db.get(User, uid)
    if not u or u.token_version != ver:  # a reset link is single-use and dies on the next reset
        raise HTTPException(400, "This reset link is invalid or has expired.")
    u.password_hash = auth.hash_password(body.password)
    # Receiving this link proves control of the mailbox — the same proof the verify link
    # provides — so consume it as verification too. Without this, bumping token_version
    # below would kill the registration verify link (the only one ever minted) and, with
    # REQUIRE_EMAIL_VERIFICATION, lock the account out permanently.
    u.email_verified = True
    u.token_version += 1  # revoke every existing session + this now-used reset link
    db.commit()
    return {"ok": True}


class TokenIn(BaseModel):
    token: str


@router.post("/verify")
def verify(body: TokenIn, response: Response, db: Session = Depends(get_db)):
    claims = auth.read_token(body.token, purpose="verify")
    if claims is None:
        raise HTTPException(400, "This verification link is invalid or has expired.")
    uid, ver = claims
    u = db.get(User, uid)
    if not u or u.token_version != ver:
        raise HTTPException(400, "This verification link is invalid or has expired.")
    u.email_verified = True
    db.commit()
    _set_cookie(response, u)  # verifying signs you in
    return _public(u)
