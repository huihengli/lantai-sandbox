"""代扣协议：银行侧只维护"谁被授权从哪个账户扣多少"，并提供列表与取消。
订阅识别、续费提醒由 Agent 基于协议列表与流水自行完成。"""
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import clock
from app.errors import LantaiError
from app.models import Account, AutopayPlan, User
from app.money import fmt, mask
from app.risk import engine
from app.services import account as acct
from app.services import audit, events
from app.services.plan import Plan

CYCLE_TEXT = {"monthly": "每月", "yearly": "每年", "weekly": "每周"}


def view(m: AutopayPlan) -> dict:
    return {"id": m.id, "account_id": m.account_id, "merchant": m.merchant, "merchant_category": m.merchant_category,
            "amount": fmt(m.amount_cents), "cycle": m.cycle, "next_debit_date": m.next_debit_date.isoformat(),
            "status": m.status, "cancelled_at": clock.iso(m.cancelled_at)}


def list_mandates(db: Session, user_id: str, status: str | None = None) -> list[AutopayPlan]:
    stmt = select(AutopayPlan).where(AutopayPlan.account_id.in_(select(Account.id).where(Account.user_id == user_id)))
    if status:
        stmt = stmt.where(AutopayPlan.status == status)
    return list(db.scalars(stmt.order_by(AutopayPlan.next_debit_date, AutopayPlan.id)))


def _owned(db: Session, user_id: str, mandate_id: str, lock: bool = False) -> AutopayPlan:
    stmt = select(AutopayPlan).where(AutopayPlan.id == mandate_id)
    m = db.scalar(stmt.with_for_update() if lock else stmt)
    if m is None or db.get(Account, m.account_id).user_id != user_id:
        raise LantaiError("RESOURCE_NOT_OWNED", "代扣协议不存在")
    return m


def normalize_cancel(db: Session, user: User, body) -> dict:
    return {"mandate_id": body.mandate_id}


def build_cancel_plan(db: Session, user: User, params: dict, now, lock: bool = False) -> Plan:
    m = _owned(db, user.id, params["mandate_id"], lock)
    if m.status != "active":
        raise LantaiError("MANDATE_NOT_ACTIVE", "该代扣协议已取消")
    acc = acct.get_owned_account(db, user.id, m.account_id, require_active=False)
    summary = {"action": "取消代扣协议", "account": f"{acct.TYPE_LABEL.get(acc.type, acc.type)} {mask(acc.account_no)}",
               "merchant": m.merchant, "amount": fmt(m.amount_cents),
               "change": f"{CYCLE_TEXT.get(m.cycle, m.cycle)}扣款；下次扣款日 {m.next_debit_date.isoformat()}；取消后商户无法继续扣款"}
    rctx = engine.build_context(db, user.id, acc, "mandate_cancel", 0, now,
                                change={"merchant": m.merchant, "date": m.next_debit_date.isoformat()})
    return Plan("mandate_cancel", params, summary, engine.evaluate(rctx), {"mandate": m})


def execute_cancel(db: Session, op, plan: Plan, now) -> dict:
    m = plan.data["mandate"]
    m.status, m.cancelled_at = "cancelled", now
    events.emit(db, db.get(Account, m.account_id).user_id, "mandate", m.id,
                {"mandate_id": m.id, "merchant": m.merchant, "status": m.status})
    return {"mandate_id": m.id, "merchant": m.merchant, "status": m.status, "executed_at": clock.iso(now)}


def charge(ctx: audit.Ctx, mandate_id: str) -> dict:
    """演示用：模拟商户发起一次代扣，生成可被 Agent 识别的周期性流水，并顺延下次扣款日。"""
    db = ctx.db
    m = db.get(AutopayPlan, mandate_id)
    if m is None:
        raise LantaiError("VALIDATION_ERROR", "代扣协议不存在")
    if m.status != "active":
        raise LantaiError("MANDATE_NOT_ACTIVE", "该代扣协议已取消，商户无法扣款")
    acc = db.get(Account, m.account_id)
    now = clock.now()
    acct.debit(db, acc, m.amount_cents)
    txn = acct.add_txn(db, acc, "out", "autopay", m.amount_cents, now, counterparty=m.merchant,
                       memo="代扣", merchant_category=m.merchant_category)
    step = {"weekly": 7, "yearly": 365}.get(m.cycle, 30)
    m.next_debit_date = m.next_debit_date + timedelta(days=step)
    audit.log(ctx, "mandate_charge", detail={"mandate_id": m.id, "txn": txn.id})
    return {"transaction_id": txn.id, "balance_after": fmt(acc.balance_cents), "next_debit_date": m.next_debit_date.isoformat()}
