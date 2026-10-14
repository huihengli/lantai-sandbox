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

from app import clock, config
from app.db import get_db
from app.errors import LantaiError
from app.models import AuthToken, User
from app.money import new_id
from app.security import ratelimit
from app.services import audit, deposit

USER_SCOPES = ["read", "prepare", "protect", "confirm", "otp", "grant"]
AGENT_ALLOWED_SCOPES = {"read", "prepare", "protect"}  # protect：仅限收紧类（保护性）直接操作
# 确认执行器：独立于 LLM Agent 的确定性程序，弹出确认框由用户手动确认后才调用；令牌只能用于 /api/exec
EXECUTOR_ALLOWED_SCOPES = {"confirm", "otp"}
_ACTOR = {"agent_token": "agent", "executor_token": "executor", "user_session": "user"}
_PREFIX = {"user_session": ("lt_u_", "ses"), "agent_token": ("lt_a_", "grt"), "executor_token": ("lt_x_", "exe")}


def channel_of(path: str) -> str:
    return "ui" if path.startswith("/ui") else "exec" if path.startswith("/api/exec") else "api"


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
        return _ACTOR.get(self.token.kind, "user")


LEGACY_ITERATIONS = 10_000  # 旧格式 "salt$digest" 的迭代次数


def hash_password(password: str, salt: str | None = None, iterations: int | None = None) -> str:
    """新格式 pbkdf2$迭代次数$盐$摘要；盐 16 字节随机。"""
    salt = salt or os.urandom(16).hex()
    n = iterations or config.PASSWORD_ITERATIONS
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), n).hex()
    return f"pbkdf2${n}${salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    if stored.startswith("pbkdf2$"):
        _, n, salt, _ = stored.split("$", 3)
        return hmac.compare_digest(hash_password(password, salt, int(n)), stored)
    salt, digest = stored.split("$", 1)  # 旧格式
    legacy = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), LEGACY_ITERATIONS).hex()
    return hmac.compare_digest(legacy, digest)


def needs_rehash(stored: str) -> bool:
    return not stored.startswith(f"pbkdf2${config.PASSWORD_ITERATIONS}$")


# 用户不存在时也做一次等价哈希，消除时序差（延迟计算，避免导入期开销）
_DUMMY: str | None = None


def burn_password_check(password: str) -> None:
    global _DUMMY
    if _DUMMY is None:
        _DUMMY = hash_password("dummy-password")
    verify_password(password, _DUMMY)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def issue_token(db: Session, kind: str, user_id: str, scopes: list[str], ttl_seconds: int,
                issued_by: str | None = None) -> tuple[str, AuthToken]:
    prefix, id_prefix = _PREFIX[kind]
    plain = prefix + secrets.token_urlsafe(24)
    now = clock.now()
    row = AuthToken(
        id=new_id(id_prefix), token_hash=_hash_token(plain),
        kind=kind, user_id=user_id, scopes=",".join(scopes), issued_by=issued_by,
        expires_at=now + timedelta(seconds=ttl_seconds), created_at=now,
    )
    db.add(row)
    return plain, row


def _deny(db: Session, request: Request, code: str, message: str, user_id: str | None = None,
          actor: str = "agent") -> LantaiError:
    ctx = audit.Ctx(db, getattr(request.state, "request_id", ""), user_id, actor,
                    channel_of(request.url.path), **client_info(request))
    audit.log(ctx, f"access_denied {request.method} {request.url.path}", "rejected", error_code=code,
              detail={"message": message})
    db.commit()
    return LantaiError(code, message)


def require(scope: str | None = None, ui_only: bool = False, executor_only: bool = False):
    """FastAPI 依赖工厂。ui_only=True 仅允许用户会话；executor_only=True 仅允许确认执行器令牌。
    执行器令牌只能访问 executor_only 接口，其余通道一律拒绝。"""

    def dependency(request: Request, db: Session = Depends(get_db)) -> Principal:
        header = request.headers.get("authorization", "")
        if not header.lower().startswith("bearer "):
            raise _deny(db, request, "AUTH_INVALID", "缺少或无效的 Authorization 令牌", actor="unknown")
        row = db.scalar(select(AuthToken).where(AuthToken.token_hash == _hash_token(header[7:].strip())))
        if row is None:
            raise _deny(db, request, "AUTH_INVALID", "令牌无效", actor="unknown")
        actor = _ACTOR.get(row.kind, "user")
        if row.revoked_at is not None:
            raise _deny(db, request, "AUTH_REVOKED", "令牌已被撤销", row.user_id, actor)
        if row.expires_at <= clock.now():
            raise _deny(db, request, "AUTH_EXPIRED", "令牌已过期", row.user_id, actor)
        if ui_only and row.kind != "user_session":
            raise _deny(db, request, "CHANNEL_NOT_ALLOWED",
                        "该接口仅限用户界面通道，Agent 令牌不可调用", row.user_id, actor)
        if executor_only and row.kind != "executor_token":
            raise _deny(db, request, "CHANNEL_NOT_ALLOWED", "该接口仅限确认执行器令牌调用", row.user_id, actor)
        if row.kind == "executor_token" and not executor_only:
            raise _deny(db, request, "CHANNEL_NOT_ALLOWED", "确认执行器令牌只能调用 /api/exec 接口", row.user_id, actor)
        scopes = set(row.scopes.split(","))
        if scope and scope not in scopes:
            raise _deny(db, request, "SCOPE_INSUFFICIENT", f"令牌缺少 {scope} 权限", row.user_id, actor)
        user = db.get(User, row.user_id)
        if user is None or user.status != "active":
            raise _deny(db, request, "USER_FROZEN", "用户已被冻结", row.user_id, actor)
        ratelimit.check(f"tok:{row.id}", config.TOKEN_RATE_LIMIT, config.TOKEN_RATE_WINDOW)
        if deposit.settle_matured(db, user.id, clock.now()):
            db.commit()  # 到期定期兑付入账
        return Principal(user=user, token=row, scopes=scopes)

    return dependency


def client_info(request: Request) -> dict:
    return {"ip": request.client.host if request.client else None, "ua": request.headers.get("user-agent")}


def make_ctx(request: Request, db: Session, p: Principal, agent_intent: str | None = None) -> audit.Ctx:
    return audit.Ctx(db, request.state.request_id, p.user.id, p.actor,
                     channel_of(request.url.path), agent_intent, **client_info(request))


def expired(dt: datetime) -> bool:
    return dt <= clock.now()
