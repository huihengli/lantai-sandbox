"""令牌签发/校验、scope 与通道隔离。"""
import hashlib
import hmac
import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import clock
from app.db import get_db
from app.errors import LantaiError
from app.models import AuthToken, User
from app.money import new_id
from app.services import audit

USER_SCOPES = ["read", "prepare", "confirm", "otp", "grant"]
AGENT_ALLOWED_SCOPES = {"read", "prepare"}


@dataclass
class Principal:
    user: User
    token: AuthToken
    scopes: set[str]

    @property
    def kind(self) -> str:
        return self.token.kind

    @property
    def actor(self) -> str:
        return "agent" if self.token.kind == "agent_token" else "user"


def hash_password(password: str, salt: str | None = None) -> str:
    salt = salt or os.urandom(8).hex()
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 10_000).hex()
    return f"{salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    salt, _ = stored.split("$", 1)
    return hmac.compare_digest(hash_password(password, salt), stored)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def issue_token(db: Session, kind: str, user_id: str, scopes: list[str], ttl_seconds: int,
                issued_by: str | None = None) -> tuple[str, AuthToken]:
    plain = ("lt_u_" if kind == "user_session" else "lt_a_") + secrets.token_urlsafe(24)
    now = clock.now()
    row = AuthToken(
        id=new_id("grt" if kind == "agent_token" else "ses"), token_hash=_hash_token(plain),
        kind=kind, user_id=user_id, scopes=",".join(scopes), issued_by=issued_by,
        expires_at=now + timedelta(seconds=ttl_seconds), created_at=now,
    )
    db.add(row)
    return plain, row


def _deny(db: Session, request: Request, code: str, message: str, user_id: str | None = None,
          actor: str = "agent") -> LantaiError:
    ctx = audit.Ctx(db, getattr(request.state, "request_id", ""), user_id, actor,
                    "ui" if request.url.path.startswith("/ui") else "api")
    audit.log(ctx, f"access_denied {request.method} {request.url.path}", "rejected", error_code=code,
              detail={"message": message})
    db.commit()
    return LantaiError(code, message)


def require(scope: str | None = None, ui_only: bool = False):
    """FastAPI 依赖工厂。ui_only=True 表示仅允许用户通道令牌（user_session）。"""

    def dependency(request: Request, db: Session = Depends(get_db)) -> Principal:
        header = request.headers.get("authorization", "")
        if not header.lower().startswith("bearer "):
            raise _deny(db, request, "AUTH_INVALID", "缺少或无效的 Authorization 令牌", actor="unknown")
        row = db.scalar(select(AuthToken).where(AuthToken.token_hash == _hash_token(header[7:].strip())))
        if row is None:
            raise _deny(db, request, "AUTH_INVALID", "令牌无效", actor="unknown")
        actor = "agent" if row.kind == "agent_token" else "user"
        if row.revoked_at is not None:
            raise _deny(db, request, "AUTH_REVOKED", "令牌已被撤销", row.user_id, actor)
        if row.expires_at <= clock.now():
            raise _deny(db, request, "AUTH_EXPIRED", "令牌已过期", row.user_id, actor)
        if ui_only and row.kind != "user_session":
            raise _deny(db, request, "CHANNEL_NOT_ALLOWED",
                        "该接口仅限用户界面通道，Agent 令牌不可调用", row.user_id, actor)
        scopes = set(row.scopes.split(","))
        if scope and scope not in scopes:
            raise _deny(db, request, "SCOPE_INSUFFICIENT", f"令牌缺少 {scope} 权限", row.user_id, actor)
        user = db.get(User, row.user_id)
        if user is None or user.status != "active":
            raise _deny(db, request, "USER_FROZEN", "用户已被冻结", row.user_id, actor)
        return Principal(user=user, token=row, scopes=scopes)

    return dependency


def make_ctx(request: Request, db: Session, p: Principal, agent_intent: str | None = None) -> audit.Ctx:
    return audit.Ctx(db, request.state.request_id, p.user.id, p.actor,
                     "ui" if request.url.path.startswith("/ui") else "api", agent_intent)


def expired(dt: datetime) -> bool:
    return dt <= clock.now()
