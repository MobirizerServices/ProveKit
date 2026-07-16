"""Auth endpoints: register / login / logout / me (email + password).

Sessions are httpOnly cookies carrying a signed token. GitHub OAuth is a planned
provider; the User model + session layer are provider-agnostic so it slots in later.
"""
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import get_db
from ..models import User
from ..services import auth

router = APIRouter(prefix="/api/auth", tags=["auth"])


class Credentials(BaseModel):
    email: EmailStr
    password: str
    name: str = ""


def _set_cookie(resp: Response, uid: int) -> None:
    resp.set_cookie(auth.COOKIE, auth.make_token(uid), max_age=auth._TTL, httponly=True,
                    samesite="lax", secure=get_settings().hosted, path="/")


def _public(u: User) -> dict:
    return {"id": u.id, "email": u.email, "name": u.name, "auth_provider": u.auth_provider}


@router.post("/register")
def register(body: Credentials, response: Response, db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == body.email).first():
        raise HTTPException(409, "An account with that email already exists")
    if len(body.password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters")
    u = User(email=body.email, name=body.name or body.email.split("@")[0],
             password_hash=auth.hash_password(body.password))
    db.add(u); db.commit(); db.refresh(u)
    _set_cookie(response, u.id)
    return _public(u)


@router.post("/login")
def login(body: Credentials, response: Response, db: Session = Depends(get_db)):
    u = db.query(User).filter(User.email == body.email).first()
    if not u or not u.password_hash or not auth.verify_password(body.password, u.password_hash):
        raise HTTPException(401, "Invalid email or password")
    _set_cookie(response, u.id)
    return _public(u)


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(auth.COOKIE, path="/")
    return {"ok": True}


@router.get("/me")
def me(user: User = Depends(auth.get_current_user)):
    return _public(user)
