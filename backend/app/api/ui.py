"""用户通道 /ui：登录、授权 Agent、OTP、确认。Agent 令牌无权调用这里的任何接口。"""
import json
from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import clock, config
from app.api.common import ok
from app.db import get_db
from app.errors import LantaiError
from app.models import AuditLog, AuthToken, User
from app.schemas import GrantIn, LoginIn, OtpIn
from app.security import auth
from app.security.auth import Principal, make_ctx, require
from app.services import audit, operation

router = APIRouter(prefix="/ui", tags=["ui"])

READ = Depends(require("read", ui_only=True))


@router.post("/login")
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)):
    ctx = audit.Ctx(db, request.state.request_id, None, "user", "ui")

    def run():
        user = db.scalar(select(User).where(User.phone == body.phone))
        if user is None or not auth.verify_password(body.password, user.password_hash):
            raise LantaiError("AUTH_INVALID", "手机号或密码错误")
        if user.status != "active":
            raise LantaiError("USER_FROZEN", "用户已被冻结")
        ctx.user_id = user.id
        token, row = auth.issue_token(db, "user_session", user.id, auth.USER_SCOPES,
                                      config.USER_SESSION_TTL_SECONDS)
        audit.log(ctx, "login")
        return {"session_token": token, "expires_at": clock.iso(row.expires_at),
                "user": {"id": user.id, "name": user.name, "phone_masked": user.phone_masked}}

    return ok(request, audit.guarded(ctx, "login", run))


@router.post("/logout")
def logout(request: Request, p: Principal = READ, db: Session = Depends(get_db)):
    ctx = make_ctx(request, db, p)

    def run():
        p.token.revoked_at = clock.now()
        audit.log(ctx, "logout")
        return {"logged_out": True}

    return ok(request, audit.guarded(ctx, "logout", run))


@router.post("/agent-grants")
def create_grant(body: GrantIn, request: Request, p: Principal = Depends(require("grant", ui_only=True)),
                 db: Session = Depends(get_db)):
    ctx = make_ctx(request, db, p)

    def run():
        bad = set(body.scopes) - auth.AGENT_ALLOWED_SCOPES
        if bad or not body.scopes:
            raise LantaiError("SCOPE_INSUFFICIENT", f"Agent 令牌只能包含 read/prepare，拒绝: {sorted(bad)}")
        ttl = min(body.ttl_seconds or config.AGENT_TOKEN_TTL_SECONDS, config.AGENT_TOKEN_MAX_TTL_SECONDS)
        token, row = auth.issue_token(db, "agent_token", p.user.id, sorted(set(body.scopes)), ttl,
                                      issued_by=p.token.id)
        audit.log(ctx, "grant_agent_token", detail={"grant_id": row.id, "scopes": body.scopes})
        return {"grant_id": row.id, "agent_token": token, "scopes": sorted(set(body.scopes)),
                "expires_at": clock.iso(row.expires_at)}

    return ok(request, audit.guarded(ctx, "grant_agent_token", run))


@router.get("/agent-grants")
def list_grants(request: Request, p: Principal = READ, db: Session = Depends(get_db)):
    rows = db.scalars(select(AuthToken).where(AuthToken.user_id == p.user.id, AuthToken.kind == "agent_token")
                      .order_by(AuthToken.created_at.desc()).limit(50))
    return ok(request, [{"grant_id": r.id, "scopes": r.scopes.split(","), "expires_at": clock.iso(r.expires_at),
                         "revoked": r.revoked_at is not None} for r in rows])


@router.delete("/agent-grants/{grant_id}")
def revoke_grant(grant_id: str, request: Request, p: Principal = Depends(require("grant", ui_only=True)),
                 db: Session = Depends(get_db)):
    ctx = make_ctx(request, db, p)

    def run():
        row = db.get(AuthToken, grant_id)
        if row is None or row.user_id != p.user.id or row.kind != "agent_token":
            raise LantaiError("RESOURCE_NOT_OWNED", "授权不存在")
        row.revoked_at = row.revoked_at or clock.now()
        audit.log(ctx, "revoke_agent_token", detail={"grant_id": grant_id})
        return {"grant_id": grant_id, "revoked": True}

    return ok(request, audit.guarded(ctx, "revoke_agent_token", run))


@router.get("/operations")
def list_operations(request: Request, status: str | None = None, p: Principal = READ,
                    db: Session = Depends(get_db)):
    return ok(request, [operation.view(o) for o in operation.list_ops(db, p.user.id, status)])


@router.get("/operations/{op_id}")
def get_operation(op_id: str, request: Request, p: Principal = READ, db: Session = Depends(get_db)):
    return ok(request, operation.view(operation.get_op(db, p.user.id, op_id)))


@router.get("/operations/{op_id}/otp-hint")
def otp_hint(op_id: str, request: Request, p: Principal = Depends(require("otp", ui_only=True)),
             db: Session = Depends(get_db)):
    return ok(request, operation.otp_hint(db, p.user, op_id))


@router.post("/operations/{op_id}/verify-otp")
def verify_otp(op_id: str, body: OtpIn, request: Request,
               p: Principal = Depends(require("otp", ui_only=True)), db: Session = Depends(get_db)):
    ctx = make_ctx(request, db, p)
    return ok(request, audit.guarded(ctx, "otp_verify", lambda: operation.verify_otp(ctx, p.user, op_id, body.code),
                                     op_id))


@router.post("/operations/{op_id}/confirm")
def confirm(op_id: str, request: Request, p: Principal = Depends(require("confirm", ui_only=True)),
            db: Session = Depends(get_db)):
    ctx = make_ctx(request, db, p)
    return ok(request, audit.guarded(ctx, "confirm", lambda: operation.confirm(ctx, p.user, op_id), op_id))


@router.post("/operations/{op_id}/reject")
def reject(op_id: str, request: Request, p: Principal = Depends(require("confirm", ui_only=True)),
           db: Session = Depends(get_db)):
    ctx = make_ctx(request, db, p)
    return ok(request, audit.guarded(ctx, "reject", lambda: operation.cancel(ctx, p.user, op_id, "reject"), op_id))


def audit_row(r: AuditLog) -> dict:
    return {"id": r.id, "ts": clock.iso(r.ts), "user_id": r.user_id, "actor": r.actor, "channel": r.channel,
            "action": r.action, "operation_id": r.operation_id, "agent_intent": r.agent_intent,
            "risk": json.loads(r.risk_json) if r.risk_json else None, "result": r.result,
            "error_code": r.error_code, "detail": json.loads(r.detail_json) if r.detail_json else None,
            "request_id": r.request_id}


@router.get("/audit")
def my_audit(request: Request, p: Principal = READ, db: Session = Depends(get_db)):
    rows = db.scalars(select(AuditLog).where(AuditLog.user_id == p.user.id).order_by(AuditLog.id.desc()).limit(100))
    return ok(request, [audit_row(r) for r in rows])
