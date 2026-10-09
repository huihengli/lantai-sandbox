"""风控引擎：构建一次上下文，跑完全部适用规则（不短路），取最高级别。"""
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import clock, config
from app.models import Account, AutopayPlan, Transaction
from app.risk import rules
from app.risk.codes import SEVERITY_ORDER
from app.risk.context import RiskContext

_ACTION = {"low": "confirm", "medium": "otp", "high": "otp", "blocked": "block"}


def build_context(db: Session, user_id: str, account: Account, op_type: str, amount_cents: int,
                  now, fee_cents: int = 0, **extra) -> RiskContext:
    out_of_user = (Transaction.direction == "out") & (Transaction.category == "transfer") & \
        Transaction.account_id.in_(select(Account.id).where(Account.user_id == user_id))
    today_out = db.scalar(select(func.coalesce(func.sum(Transaction.amount_cents), 0)).where(
        Transaction.account_id == account.id, Transaction.direction == "out",
        Transaction.category == "transfer", Transaction.occurred_at >= clock.local_day_start_utc(now)))
    recent = db.scalar(select(func.count()).select_from(Transaction).where(
        out_of_user, Transaction.occurred_at >= now - timedelta(seconds=config.RAPID_WINDOW_SECONDS)))
    today = clock.local(now).date()
    autopays = db.scalars(select(AutopayPlan).where(
        AutopayPlan.account_id == account.id, AutopayPlan.status == "active",
        AutopayPlan.next_debit_date >= today,
        AutopayPlan.next_debit_date <= today + timedelta(days=config.AUTOPAY_LOOKAHEAD_DAYS))).all()
    return RiskContext(
        op_type=op_type, account=account, amount_cents=amount_cents, fee_cents=fee_cents, now=now,
        local_now=clock.local(now), today_out_cents=int(today_out), recent_out_count=int(recent),
        autopays=[(a.merchant, a.amount_cents, a.next_debit_date.isoformat()) for a in autopays],
        **extra)


def evaluate(ctx: RiskContext) -> dict:
    reasons: list[dict] = []
    for op_types, fn in rules.RULES:
        if ctx.op_type in op_types:
            reasons.extend(fn(ctx))
    level = max((r["severity"] for r in reasons), key=SEVERITY_ORDER.__getitem__, default="low")
    return {"level": level, "required_action": _ACTION[level], "reasons": reasons}
