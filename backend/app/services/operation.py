"""两阶段操作状态机：prepare → (OTP) → confirm，以及取消/拒绝/过期。"""
import hashlib
import json
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import clock, config
from app.errors import LantaiError
from app.models import PendingOperation, User
from app.money import new_id
from app.security import otp
from app.services import audit, deposit, idempotency, transfer

ACTIVE = {"PREPARED", "OTP_PENDING", "OTP_VERIFIED"}

NORMALIZE = {"transfer": transfer.normalize, "deposit_create": deposit.normalize_create,
             "deposit_early_withdraw": deposit.normalize_early}
BUILD = {"transfer": transfer.build_plan, "deposit_create": deposit.build_create_plan,
         "deposit_early_withdraw": deposit.build_early_plan}
EXECUTE = {"transfer": transfer.execute, "deposit_create": deposit.execute_create,
           "deposit_early_withdraw": deposit.execute_early}


def params_hash(params: dict) -> str:
    return hashlib.sha256(json.dumps(params, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def view(op: PendingOperation) -> dict:
    out = {
        "operation_id": op.id, "type": op.type, "status": op.status, "initiator": op.initiator,
        "summary": json.loads(op.summary_json), "risk": json.loads(op.risk_json),
        "confirm_by": "user_interface", "expires_at": clock.iso(op.expires_at),
        "created_at": clock.iso(op.created_at),
    }
    if op.status in ACTIVE:
        out["confirm_url"] = f"{config.FRONTEND_BASE_URL}/confirm/{op.id}"
    if op.result_json:
        out["result"] = json.loads(op.result_json)
    return out


def get_op(db: Session, user_id: str, op_id: str) -> PendingOperation:
    op = db.get(PendingOperation, op_id)
    if op is None or op.user_id != user_id:
        raise LantaiError("OPERATION_NOT_FOUND", "操作不存在")
    expire_if_needed(db, op)
    return op


def expire_if_needed(db: Session, op: PendingOperation) -> None:
    if op.status in ACTIVE and op.expires_at <= clock.now():
        op.status = "EXPIRED"
        db.commit()  # 惰性过期：先落库，再由调用方决定是否报错


def list_ops(db: Session, user_id: str, status: str | None) -> list[PendingOperation]:
    stmt = select(PendingOperation).where(PendingOperation.user_id == user_id)
    if status:
        stmt = stmt.where(PendingOperation.status.in_(status.split(",")))
    ops = list(db.scalars(stmt.order_by(PendingOperation.created_at.desc()).limit(100)))
    for op in ops:
        expire_if_needed(db, op)
    return ops


def prepare(ctx: audit.Ctx, user: User, op_type: str, body, idem_key: str | None) -> dict:
    db = ctx.db
    endpoint = f"{op_type}.prepare"
    req_hash = idempotency.request_hash(body.model_dump(exclude={"idempotency_key", "agent_context"}))
    cached = idempotency.lookup(db, idem_key, user.id, endpoint, req_hash)
    if cached is not None:
        return cached

    now = clock.now()
    params = NORMALIZE[op_type](db, user, body)
    plan = BUILD[op_type](db, user, params, now)
    risk = plan.risk
    status = {"block": "BLOCKED", "otp": "OTP_PENDING"}.get(risk["required_action"], "PREPARED")
    op = PendingOperation(
        id=new_id("op"), user_id=user.id, type=op_type,
        params_json=json.dumps(params, sort_keys=True, ensure_ascii=False), params_hash=params_hash(params),
        summary_json=json.dumps(plan.summary, ensure_ascii=False), risk_level=risk["level"],
        required_action=risk["required_action"], risk_json=json.dumps(risk, ensure_ascii=False),
        status=status, initiator=ctx.actor, agent_intent=ctx.agent_intent, idempotency_key=idem_key,
        created_at=now, expires_at=now + timedelta(seconds=config.OPERATION_TTL_SECONDS))
    db.add(op)
    db.flush()
    if status == "OTP_PENDING":
        otp.issue(db, op)
    audit.log(ctx, f"prepare:{op_type}", "blocked" if status == "BLOCKED" else "ok", op.id, risk,
              detail={"summary": plan.summary})
    out = view(op)
    idempotency.store(db, idem_key, user.id, endpoint, req_hash, out)
    return out


def _fail(db: Session, op_id: str, exc: LantaiError) -> None:
    db.rollback()
    op = db.get(PendingOperation, op_id)
    op.status = "FAILED"
    op.result_json = json.dumps({"error": exc.code, "message": exc.message}, ensure_ascii=False)
    db.commit()


def confirm(ctx: audit.Ctx, user: User, op_id: str) -> dict:
    db = ctx.db
    op = get_op(db, user.id, op_id)
    if op.status == "EXECUTED":
        return view(op)
    if op.status == "EXPIRED":
        raise LantaiError("OPERATION_EXPIRED", "操作已过期，请重新发起")
    if op.status == "BLOCKED":
        raise LantaiError("RISK_BLOCKED", "该操作已被风控拦截，无法确认")
    if op.status == "OTP_LOCKED":
        raise LantaiError("OTP_LOCKED", "OTP 已锁定，请重新发起操作")
    if op.status not in ACTIVE:
        raise LantaiError("OPERATION_STATE_INVALID", f"当前状态 {op.status} 不可确认")
    params = json.loads(op.params_json)
    if params_hash(params) != op.params_hash:
        raise LantaiError("PARAMS_TAMPERED", "操作参数与预处理时不一致")

    now = clock.now()
    try:
        plan = BUILD[op.type](db, user, params, now, lock=True)
    except LantaiError as exc:
        _fail(db, op_id, exc)
        raise
    risk = plan.risk
    op.risk_json, op.risk_level, op.required_action = json.dumps(risk, ensure_ascii=False), risk["level"], risk["required_action"]
    if risk["required_action"] == "block":
        op.status = "BLOCKED"
        db.commit()
        raise LantaiError("RISK_BLOCKED", "确认时风控复核未通过", {"reasons": risk["reasons"]})
    if risk["required_action"] == "otp" and op.status != "OTP_VERIFIED":
        if op.status != "OTP_PENDING":
            op.status = "OTP_PENDING"
            otp.issue(db, op)
        db.commit()
        raise LantaiError("OTP_REQUIRED", "该操作需要先通过 OTP 验证")

    try:
        result = EXECUTE[op.type](db, op, plan, now)
    except LantaiError as exc:
        _fail(db, op_id, exc)
        raise
    op.status, op.confirmed_at, op.executed_at = "EXECUTED", now, now
    op.result_json = json.dumps(result, ensure_ascii=False)
    audit.log(ctx, f"confirm:{op.type}", operation_id=op.id, risk=risk, detail=result)
    return view(op)


def verify_otp(ctx: audit.Ctx, user: User, op_id: str, code: str) -> dict:
    op = get_op(ctx.db, user.id, op_id)
    if op.status == "OTP_VERIFIED":
        return view(op)
    if op.status == "EXPIRED":
        raise LantaiError("OPERATION_EXPIRED", "操作已过期，请重新发起")
    if op.status == "OTP_LOCKED":
        raise LantaiError("OTP_LOCKED", "OTP 已锁定，请重新发起操作")
    if op.status != "OTP_PENDING":
        raise LantaiError("OPERATION_STATE_INVALID", f"当前状态 {op.status} 无需验证 OTP")
    otp.verify(ctx, op, code)
    return view(op)


def otp_hint(db: Session, user: User, op_id: str) -> dict:
    op = get_op(db, user.id, op_id)
    ch = otp.latest(db, op.id)
    if op.status != "OTP_PENDING" or ch is None:
        raise LantaiError("OPERATION_STATE_INVALID", "该操作当前没有待验证的 OTP")
    return {"sms": f"【澜台】验证码 {ch.demo_code}，5 分钟内有效，请勿向任何人透露。",
            "attempts_left": ch.max_attempts - ch.attempts}


def cancel(ctx: audit.Ctx, user: User, op_id: str, action: str) -> dict:
    op = get_op(ctx.db, user.id, op_id)
    if op.status == "CANCELLED":
        return view(op)
    if op.status not in ACTIVE:
        raise LantaiError("OPERATION_STATE_INVALID", f"当前状态 {op.status} 不可取消")
    op.status = "CANCELLED"
    audit.log(ctx, action, operation_id=op.id)
    return view(op)
