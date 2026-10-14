"""两阶段操作状态机：prepare → (OTP) → confirm，以及取消/拒绝/过期。"""
import hashlib
import json
from datetime import timedelta

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app import clock, config
from app.errors import LantaiError
from app.models import PendingOperation, User
from app.money import new_id
from app.security import otp, ratelimit
from app.services import audit, cards, events, deposit, holds, idempotency, mandates, payments, transfer, wealth

ACTIVE = {"PREPARED", "OTP_PENDING", "OTP_VERIFIED"}

NORMALIZE = {"transfer": transfer.normalize, "deposit_create": deposit.normalize_create,
             "deposit_early_withdraw": deposit.normalize_early,
             "card_apply": cards.normalize_apply, "card_unfreeze": cards.normalize_card_only,
             "card_reissue": cards.normalize_card_only, "card_report_loss": cards.normalize_card_only, "card_controls": cards.normalize_controls,
             "card_limits": cards.normalize_limits, "account_limits": cards.normalize_limits,
             "mandate_cancel": mandates.normalize_cancel, "hold_release": holds.normalize_release,
             "merchant_payment": payments.normalize, "wealth_subscribe": wealth.normalize_subscribe,
             "wealth_redeem": wealth.normalize_redeem}
BUILD = {"transfer": transfer.build_plan, "deposit_create": deposit.build_create_plan,
         "deposit_early_withdraw": deposit.build_early_plan,
         "card_apply": cards.build_apply_plan, "card_unfreeze": cards.build_unfreeze_plan,
         "card_reissue": cards.build_reissue_plan, "card_report_loss": cards.build_report_loss_plan, "card_controls": cards.build_controls_plan,
         "card_limits": cards.build_card_limits_plan, "account_limits": cards.build_account_limits_plan,
         "mandate_cancel": mandates.build_cancel_plan, "hold_release": holds.build_release_plan,
         "merchant_payment": payments.build_plan, "wealth_subscribe": wealth.build_subscribe_plan,
         "wealth_redeem": wealth.build_redeem_plan}
EXECUTE = {"transfer": transfer.execute, "deposit_create": deposit.execute_create,
           "deposit_early_withdraw": deposit.execute_early,
           "card_apply": cards.execute_apply, "card_unfreeze": cards.execute_unfreeze,
           "card_reissue": cards.execute_reissue, "card_report_loss": cards.execute_report_loss, "card_controls": cards.execute_controls,
           "card_limits": cards.execute_card_limits, "account_limits": cards.execute_account_limits,
           "mandate_cancel": mandates.execute_cancel, "hold_release": holds.execute_release,
           "merchant_payment": payments.execute, "wealth_subscribe": wealth.execute_subscribe,
           "wealth_redeem": wealth.execute_redeem}


def params_hash(params: dict) -> str:
    return hashlib.sha256(json.dumps(params, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


# Agent 通道不得经风控文案反推余额/当日累计/自动扣款明细（这些需 read 权限与用户界面才能看）
_AGENT_NEUTRAL = {
    "DAILY_LIMIT_EXCEEDED": ("超过账户单日累计转出限额", "告知用户今日额度已不足，建议明日再试"),
    "CARD_LIMIT_EXCEEDED": ("超过卡片额度限制", "建议用户在确认中心查看额度，分日或提额（需验证）"),
    "AUTOPAY_AT_RISK": ("转出后余额可能不足以覆盖近期自动扣款", "提醒用户到界面查看扣款计划"),
}
_AGENT_STRIP = ("balance_after",)


def neutral_reasons(reasons: list[dict]) -> list[dict]:
    """敏感风控原因改为中性文案并清空 params（供会进入 LLM 上下文的响应使用）。"""
    return [{**r, "message": _AGENT_NEUTRAL[r["code"]][0], "agent_hint": _AGENT_NEUTRAL[r["code"]][1], "params": {}}
            if r["code"] in _AGENT_NEUTRAL else r for r in reasons]


def trim_for_llm(out: dict) -> dict:
    """按 Agent 视图裁剪：去掉余额类字段、中性化敏感风控原因。Agent 通道与执行器回写结果共用。"""
    out["summary"] = {k: v for k, v in out["summary"].items() if k not in _AGENT_STRIP}
    if "result" in out and isinstance(out["result"], dict):
        out["result"] = {k: v for k, v in out["result"].items() if k not in _AGENT_STRIP}
    out["risk"] = {**out["risk"], "reasons": neutral_reasons(out["risk"].get("reasons", []))}
    return out


def view(op: PendingOperation, actor: str = "user") -> dict:
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
    return trim_for_llm(out) if actor == "agent" else out


def emit_status(db: Session, op: PendingOperation) -> None:
    events.emit(db, op.user_id, "operation", op.id, {"operation_id": op.id, "op_type": op.type, "status": op.status})


def get_op(db: Session, user_id: str, op_id: str) -> PendingOperation:
    op = db.get(PendingOperation, op_id)
    if op is None or op.user_id != user_id:
        raise LantaiError("OPERATION_NOT_FOUND", "操作不存在")
    expire_if_needed(db, op)
    return op


def expire_if_needed(db: Session, op: PendingOperation) -> None:
    if op.status in ACTIVE and op.expires_at <= clock.now():
        op.status = "EXPIRED"
        emit_status(db, op)
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
    active = db.scalar(select(func.count()).select_from(PendingOperation).where(
        PendingOperation.user_id == user.id, PendingOperation.status.in_(ACTIVE), PendingOperation.expires_at > now))
    if active >= config.MAX_ACTIVE_OPERATIONS:
        raise LantaiError("TOO_MANY_PENDING", "待处理的操作过多，请先确认、取消或等待过期")
    if op_type == "transfer":
        ratelimit.check(f"probe:{user.id}", config.PREPARE_PROBE_LIMIT, config.PREPARE_PROBE_WINDOW)
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
    emit_status(db, op)
    audit.log(ctx, f"prepare:{op_type}", "blocked" if status == "BLOCKED" else "ok", op.id, risk,
              detail={"summary": plan.summary})
    out = view(op, ctx.actor)
    if not idempotency.store(db, idem_key, user.id, endpoint, req_hash, out):
        return idempotency.lookup(db, idem_key, user.id, endpoint, req_hash) or out
    return out


def _fail(db: Session, op_id: str, exc: LantaiError) -> None:
    db.rollback()
    op = db.get(PendingOperation, op_id)
    op.status = "FAILED"
    op.result_json = json.dumps({"error": exc.code, "message": exc.message}, ensure_ascii=False)
    emit_status(db, op)
    db.commit()


def _lock_op(db: Session, op: PendingOperation) -> None:
    """对操作行加写锁（条件空更新）并重读状态，使「检查状态 → 执行」在同一把锁内完成，防并发重复执行。"""
    db.execute(update(PendingOperation).where(PendingOperation.id == op.id, PendingOperation.status.in_(ACTIVE))
               .values(status=PendingOperation.status).execution_options(synchronize_session=False))
    db.refresh(op)


def confirm(ctx: audit.Ctx, user: User, op_id: str) -> dict:
    db = ctx.db
    op = get_op(db, user.id, op_id)
    _lock_op(db, op)
    if op.status == "EXECUTED":
        return view(op, ctx.actor)
    if op.status == "EXPIRED":
        raise LantaiError("OPERATION_EXPIRED", "操作已过期，请重新发起")
    if op.status == "BLOCKED":
        raise LantaiError("RISK_BLOCKED", "该操作已被风控拦截，无法确认")
    if op.status == "OTP_LOCKED":
        raise LantaiError("OTP_LOCKED", "OTP 已锁定，请重新发起操作")
    if op.status not in ACTIVE:
        raise LantaiError("OPERATION_STATE_INVALID", f"当前状态 {op.status} 不可确认")
    params = json.loads(op.params_json)  # confirm 不接受任何新参数，TOCTOU 由此保证；params_hash 仅作留痕

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
        emit_status(db, op)
        db.commit()
        # 执行器通道的结果会回写进 Agent 上下文，原因按 Agent 视图中性化
        reasons = neutral_reasons(risk["reasons"]) if ctx.channel == "exec" else risk["reasons"]
        raise LantaiError("RISK_BLOCKED", "确认时风控复核未通过", {"reasons": reasons})
    if risk["required_action"] == "otp" and op.status != "OTP_VERIFIED":
        if op.status != "OTP_PENDING":
            op.status = "OTP_PENDING"
            otp.issue(db, op)
            emit_status(db, op)
        db.commit()
        raise LantaiError("OTP_REQUIRED", "该操作需要先通过 OTP 验证")

    try:
        result = EXECUTE[op.type](db, op, plan, now)
    except LantaiError as exc:
        _fail(db, op_id, exc)
        raise
    op.status, op.confirmed_at, op.executed_at = "EXECUTED", now, now
    emit_status(db, op)
    op.result_json = json.dumps(result, ensure_ascii=False)
    audit.log(ctx, f"confirm:{op.type}", operation_id=op.id, risk=risk, detail=result)
    return view(op, ctx.actor)


def verify_otp(ctx: audit.Ctx, user: User, op_id: str, code: str) -> dict:
    op = get_op(ctx.db, user.id, op_id)
    if op.status == "OTP_VERIFIED":
        return view(op, ctx.actor)
    if op.status == "EXPIRED":
        raise LantaiError("OPERATION_EXPIRED", "操作已过期，请重新发起")
    if op.status == "OTP_LOCKED":
        raise LantaiError("OTP_LOCKED", "OTP 已锁定，请重新发起操作")
    if op.status != "OTP_PENDING":
        raise LantaiError("OPERATION_STATE_INVALID", f"当前状态 {op.status} 无需验证 OTP")
    otp.verify(ctx, op, code)
    return view(op, ctx.actor)


def otp_hint(db: Session, user: User, op_id: str) -> dict:
    if not config.OTP_DEMO_MODE:
        raise LantaiError("NOT_FOUND", "接口不存在")
    op = get_op(db, user.id, op_id)
    ch = otp.latest(db, op.id)
    if op.status != "OTP_PENDING" or ch is None:
        raise LantaiError("OPERATION_STATE_INVALID", "该操作当前没有待验证的 OTP")
    return {"sms": f"【澜台】验证码 {ch.demo_code}，5 分钟内有效，请勿向任何人透露。",
            "attempts_left": ch.max_attempts - ch.attempts}


def cancel(ctx: audit.Ctx, user: User, op_id: str, action: str) -> dict:
    op = get_op(ctx.db, user.id, op_id)
    _lock_op(ctx.db, op)
    if op.status == "CANCELLED":
        return view(op, ctx.actor)
    if op.status not in ACTIVE:
        raise LantaiError("OPERATION_STATE_INVALID", f"当前状态 {op.status} 不可取消")
    op.status = "CANCELLED"
    emit_status(ctx.db, op)
    audit.log(ctx, action, operation_id=op.id)
    return view(op, ctx.actor)
