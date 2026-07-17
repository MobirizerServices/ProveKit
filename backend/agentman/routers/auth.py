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


def _set_cookie(resp: Response, uid: int) -> None:
    resp.set_cookie(auth.COOKIE, auth.make_token(uid), max_age=auth._TTL, httponly=True,
                    samesite="lax", secure=get_settings().hosted, path="/")


def _public(u: User) -> dict:
    return {"id": u.id, "email": u.email, "name": u.name, "auth_provider": u.auth_provider,
            "email_verified": u.email_verified}


def _send_verify(u: User) -> None:
    s = get_settings()
    token = auth.make_token(u.id, ttl=2 * 24 * 3600, purpose="verify")
    link = f"{s.web_base_url.rstrip('/')}/verify?token={token}"
    email.send(u.email, "Verify your AgentMan email",
               f"Confirm your email to finish setting up AgentMan:\n\n{link}\n\nThis link expires in 48 hours.")


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
        _set_cookie(response, u.id)  # verification optional → log in immediately
    return _public(u)


@router.post("/login")
def login(body: Credentials, request: Request, response: Response, db: Session = Depends(get_db)):
    client = request.client.host if request.client else "?"
    check_login_rate(f"{body.email}:{client}")  # brute-force throttle
    u = db.query(User).filter(User.email == body.email).first()
    if not u or not u.password_hash or not auth.verify_password(body.password, u.password_hash):
        raise HTTPException(401, "Invalid email or password")
    if get_settings().require_email_verification and not u.email_verified:
        raise HTTPException(403, "Please verify your email before signing in.")
    _set_cookie(response, u.id)
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
        token = auth.make_token(u.id, ttl=3600, purpose="reset")
        link = f"{get_settings().web_base_url.rstrip('/')}/reset?token={token}"
        email.send(u.email, "Reset your AgentMan password",
                   f"Reset your password with this link (valid 1 hour):\n\n{link}\n\n"
                   "If you didn't request this, ignore this email.")
    return {"ok": True}


class ResetIn(BaseModel):
    token: str
    password: str


@router.post("/reset")
def reset(body: ResetIn, db: Session = Depends(get_db)):
    uid = auth.read_token(body.token, purpose="reset")
    if uid is None:
        raise HTTPException(400, "This reset link is invalid or has expired.")
    if len(body.password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters")
    u = db.get(User, uid)
    if not u:
        raise HTTPException(400, "Account not found")
    u.password_hash = auth.hash_password(body.password)
    db.commit()
    return {"ok": True}


class TokenIn(BaseModel):
    token: str


@router.post("/verify")
def verify(body: TokenIn, response: Response, db: Session = Depends(get_db)):
    uid = auth.read_token(body.token, purpose="verify")
    if uid is None:
        raise HTTPException(400, "This verification link is invalid or has expired.")
    u = db.get(User, uid)
    if not u:
        raise HTTPException(400, "Account not found")
    u.email_verified = True
    db.commit()
    _set_cookie(response, u.id)  # verifying signs you in
    return _public(u)
