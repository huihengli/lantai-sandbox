"""用户通道 /ui：登录、授权 Agent、OTP、确认。Agent 令牌无权调用这里的任何接口。"""
import json
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import clock, config
from app.api.common import ok
from app.db import get_db
from app.errors import LantaiError
from app.models import AuditLog, AuthToken, User
from app.schemas import GrantIn, LoginIn, OtpIn, RiskAnswersIn
from app.security import auth, ratelimit
from app.security.auth import Principal, make_ctx, require
from app.services import audit, events, idempotency, operation, risk_profile

router = APIRouter(prefix="/ui", tags=["ui"])

READ = Depends(require("read", ui_only=True))


@router.post("/login")
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)):
    ctx = audit.Ctx(db, request.state.request_id, None, "user", "ui", **auth.client_info(request))
    ip = ctx.ip or "unknown"

    def run():
        phone_key, ip_key = f"login:{body.phone}", f"loginip:{ip}"
        if (ratelimit.is_blocked(phone_key, config.LOGIN_FAIL_LIMIT_PHONE, config.LOGIN_FAIL_WINDOW_SECONDS)
                or ratelimit.is_blocked(ip_key, config.LOGIN_FAIL_LIMIT_IP, config.LOGIN_FAIL_WINDOW_SECONDS)):
            raise LantaiError("RATE_LIMITED", "尝试次数过多，请稍后再试")
        user = db.scalar(select(User).where(User.phone == body.phone))
        if user is None:
            auth.burn_password_check(body.password)
        if user is None or not auth.verify_password(body.password, user.password_hash):
            ratelimit.record(phone_key)
            ratelimit.record(ip_key)
            raise LantaiError("AUTH_INVALID", "手机号或密码错误")
        ratelimit.clear(phone_key)
        idempotency.purge_expired(db)  # 惰性清理：过期幂等记录与过期事件
        events.purge_old(db)
        if auth.needs_rehash(user.password_hash):
            user.password_hash = auth.hash_password(body.password)
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
def logout(request: Request, revoke_grants: bool = False, p: Principal = READ, db: Session = Depends(get_db)):
    """revoke_grants=true 时同时撤销该用户全部未撤销的 Agent 令牌与确认执行器令牌。"""
    ctx = make_ctx(request, db, p)

    def run():
        now = clock.now()
        p.token.revoked_at = now
        if revoke_grants:
            for t in db.scalars(select(AuthToken).where(AuthToken.user_id == p.user.id,
                                                        AuthToken.kind.in_(("agent_token", "executor_token")),
                                                        AuthToken.revoked_at.is_(None))):
                t.revoked_at = now
        audit.log(ctx, "logout", detail={"revoke_grants": revoke_grants})
        return {"logged_out": True}

    return ok(request, audit.guarded(ctx, "logout", run))


@router.post("/agent-grants")
def create_grant(body: GrantIn, request: Request, p: Principal = Depends(require("grant", ui_only=True)),
                 db: Session = Depends(get_db)):
    ctx = make_ctx(request, db, p)

    def run():
        bad = set(body.scopes) - auth.AGENT_ALLOWED_SCOPES
        if bad or not body.scopes:
            raise LantaiError("SCOPE_INSUFFICIENT", f"Agent 令牌只能包含 read/prepare/protect，拒绝: {sorted(bad)}")
        ttl = min(body.ttl_seconds or config.AGENT_TOKEN_TTL_SECONDS, config.AGENT_TOKEN_MAX_TTL_SECONDS)
        token, row = auth.issue_token(db, "agent_token", p.user.id, sorted(set(body.scopes)), ttl,
                                      issued_by=p.token.id)
        out = {"grant_id": row.id, "agent_token": token, "scopes": sorted(set(body.scopes)),
               "expires_at": clock.iso(row.expires_at)}
        if body.with_executor:
            # 执行器令牌挂在同一授权下（issued_by=授权编号），有效期一致；只能调用 /api/exec，须由执行器程序保管
            ex_token, ex_row = auth.issue_token(db, "executor_token", p.user.id,
                                                sorted(auth.EXECUTOR_ALLOWED_SCOPES), ttl, issued_by=row.id)
            ex_row.expires_at = row.expires_at
            out.update(executor_token=ex_token, executor_scopes=sorted(auth.EXECUTOR_ALLOWED_SCOPES))
        audit.log(ctx, "grant_agent_token", detail={"grant_id": row.id, "scopes": body.scopes,
                                                    "with_executor": body.with_executor})
        return out

    return ok(request, audit.guarded(ctx, "grant_agent_token", run))


@router.get("/agent-grants")
def list_grants(request: Request, p: Principal = READ, db: Session = Depends(get_db)):
    rows = list(db.scalars(select(AuthToken).where(AuthToken.user_id == p.user.id, AuthToken.kind == "agent_token")
                           .order_by(AuthToken.created_at.desc()).limit(50)))
    with_exec = set(db.scalars(select(AuthToken.issued_by).where(
        AuthToken.user_id == p.user.id, AuthToken.kind == "executor_token",
        AuthToken.issued_by.in_([r.id for r in rows])))) if rows else set()
    return ok(request, [{"grant_id": r.id, "scopes": r.scopes.split(","), "expires_at": clock.iso(r.expires_at),
                         "executor": r.id in with_exec, "revoked": r.revoked_at is not None} for r in rows])


@router.delete("/agent-grants/{grant_id}")
def revoke_grant(grant_id: str, request: Request, p: Principal = Depends(require("grant", ui_only=True)),
                 db: Session = Depends(get_db)):
    ctx = make_ctx(request, db, p)

    def run():
        row = db.get(AuthToken, grant_id)
        if row is None or row.user_id != p.user.id or row.kind != "agent_token":
            raise LantaiError("RESOURCE_NOT_OWNED", "授权不存在")
        now = clock.now()
        row.revoked_at = row.revoked_at or now
        for ex in db.scalars(select(AuthToken).where(AuthToken.user_id == p.user.id, AuthToken.kind == "executor_token",
                                                     AuthToken.issued_by == grant_id)):
            ex.revoked_at = ex.revoked_at or now  # 绑定的执行器令牌一起撤销
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
def my_audit(request: Request, actor: str | None = Query(None, pattern="^(user|agent|executor)$"),
             p: Principal = READ, db: Session = Depends(get_db)):
    """actor 可选：只看用户 / 智能助手 / 确认执行器发起的记录（服务端过滤，不受 100 条截断影响）。"""
    stmt = select(AuditLog).where(AuditLog.user_id == p.user.id)
    if actor:
        stmt = stmt.where(AuditLog.actor == actor)
    rows = db.scalars(stmt.order_by(AuditLog.id.desc()).limit(100))
    return ok(request, [audit_row(r) for r in rows])


@router.put("/risk-profile")
def submit_risk_profile(body: RiskAnswersIn, request: Request, p: Principal = Depends(require("confirm", ui_only=True)),
                        db: Session = Depends(get_db)):
    """提交风险测评答案。等级由银行按答案计算，Agent 无法提交或指定。"""
    ctx = make_ctx(request, db, p)
    return ok(request, audit.guarded(ctx, "risk_assessment", lambda: risk_profile.assess(ctx, p.user, body.answers)))
