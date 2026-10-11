"""资金预留（圈存）：在账户内锁定一笔额度，不可被转出、存入定期、支付或代扣。

创建是"收紧"（直接生效，Agent 凭 protect 范围可做）；释放是"放宽"（走 prepare → 用户确认）。
到期自动失效（惰性：读取时转为 expired）。
"""
from datetime import datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import clock, config
from app.errors import LantaiError
from app.models import Account, Hold, User
from app.money import fmt, mask, new_id, parse_amount
from app.risk import engine
from app.services import account as acct
from app.services import audit, events
from app.services.plan import Plan


def view(h: Hold) -> dict:
    return {"id": h.id, "account_id": h.account_id, "amount": fmt(h.amount_cents), "purpose": h.purpose,
            "status": h.status, "expires_at": clock.iso(h.expires_at), "created_at": clock.iso(h.created_at),
            "released_at": clock.iso(h.released_at), "created_by": h.created_by}


def expire_due(db: Session, account_id: str) -> None:
    now = clock.now()
    for h in db.scalars(select(Hold).where(Hold.account_id == account_id, Hold.status == "active",
                                           Hold.expires_at.is_not(None), Hold.expires_at <= now)):
        h.status = "expired"
        events.emit(db, h.user_id, "hold", h.id, {"hold_id": h.id, "status": "expired", "amount": fmt(h.amount_cents)})
    db.flush()


def list_holds(db: Session, account_id: str, status: str | None = None) -> list[Hold]:
    expire_due(db, account_id)
    stmt = select(Hold).where(Hold.account_id == account_id)
    if status:
        stmt = stmt.where(Hold.status == status)
    return list(db.scalars(stmt.order_by(Hold.created_at.desc(), Hold.id)))


def _parse_until(until: str | None) -> datetime | None:
    if not until:
        return None
    try:
        dt = datetime.fromisoformat(until)
    except ValueError:
        raise LantaiError("VALIDATION_ERROR", "until 需为 ISO8601 日期或时间") from None
    if len(until) <= 10:  # 纯日期：当天 23:59:59（澜台本地）结束
        dt = datetime.combine(dt.date(), time(23, 59, 59))
    if dt.tzinfo is not None:
        from datetime import timezone
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    else:
        dt = dt - config.TZ
    now = clock.now()
    if dt <= now:
        raise LantaiError("VALIDATION_ERROR", "到期时间必须晚于当前时间")
    if dt > now + timedelta(days=config.HOLD_MAX_DAYS):
        raise LantaiError("VALIDATION_ERROR", f"预留期限最长 {config.HOLD_MAX_DAYS} 天")
    return dt


def create(ctx: audit.Ctx, user: User, account_id: str, body) -> dict:
    db = ctx.db
    acc = acct.get_owned_account(db, user.id, account_id, lock=True)
    cents = parse_amount(body.amount)
    expires = _parse_until(body.until)
    expire_due(db, acc.id)
    active = [h for h in list_holds(db, acc.id, "active")]
    if len(active) >= config.HOLD_MAX_ACTIVE:
        raise LantaiError("HOLD_LIMIT_REACHED", f"每个账户最多同时预留 {config.HOLD_MAX_ACTIVE} 笔")
    avail = acct.available_cents(db, acc)
    if cents > avail:
        raise LantaiError("INSUFFICIENT_BALANCE", "可用余额不足以预留该金额", {"available": fmt(avail)})
    h = Hold(id=new_id("hol"), user_id=user.id, account_id=acc.id, amount_cents=cents,
             purpose=(body.purpose or "资金预留")[:60], status="active", expires_at=expires,
             created_at=clock.now(), created_by=ctx.actor)
    db.add(h)
    db.flush()
    events.emit(db, user.id, "hold", h.id, {"hold_id": h.id, "status": "active", "amount": fmt(cents), "purpose": h.purpose})
    audit.log(ctx, "hold_create", detail={"hold_id": h.id, "amount": fmt(cents), "purpose": h.purpose})
    return {"hold": view(h), "available_after": fmt(avail - cents)}


# ---- 释放（prepare → 确认）----
def normalize_release(db: Session, user: User, body) -> dict:
    return {"hold_id": body.hold_id}


def build_release_plan(db: Session, user: User, params: dict, now, lock: bool = False) -> Plan:
    stmt = select(Hold).where(Hold.id == params["hold_id"])
    h = db.scalar(stmt.with_for_update() if lock else stmt)
    if h is None or h.user_id != user.id:
        raise LantaiError("RESOURCE_NOT_OWNED", "预留不存在")
    expire_due(db, h.account_id)
    if h.status != "active":
        raise LantaiError("HOLD_NOT_ACTIVE", "该预留已释放或已到期")
    acc = acct.get_owned_account(db, user.id, h.account_id, require_active=False)
    summary = {"action": "释放预留资金", "account": f"{acct.TYPE_LABEL.get(acc.type, acc.type)} {mask(acc.account_no)}",
               "amount": fmt(h.amount_cents), "change": f"用途：{h.purpose}；释放后该笔资金恢复可用"}
    rctx = engine.build_context(db, user.id, acc, "hold_release", 0, now,
                                change={"amount": fmt(h.amount_cents), "purpose": h.purpose})
    return Plan("hold_release", params, summary, engine.evaluate(rctx), {"hold": h})


def execute_release(db: Session, op, plan: Plan, now) -> dict:
    h = plan.data["hold"]
    h.status, h.released_at = "released", now
    events.emit(db, h.user_id, "hold", h.id, {"hold_id": h.id, "status": "released", "amount": fmt(h.amount_cents)})
    return {"hold_id": h.id, "status": h.status, "executed_at": clock.iso(now)}
