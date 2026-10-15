"""商户支付：用借记卡向商户付款（线上/线下/境外）。
受卡片状态、交易开关、卡片额度、商户风险、余额约束，走 prepare → 确认。
订花、订蛋糕、买会员这类场景由 Agent 在此之上编排；银行不做商户下单。"""
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import clock
from app.errors import LantaiError
from app.models import Account, Card, Merchant, Transaction, User
from app.money import fmt, mask, parse_amount
from app.risk import engine
from app.services import account as acct
from app.services import cards
from app.services.plan import Plan


def merchant_view(m: Merchant) -> dict:
    return {"id": m.id, "name": m.name, "category": m.category, "overseas": m.overseas, "description": m.description}


def list_merchants(db: Session) -> list[Merchant]:
    return list(db.scalars(select(Merchant).where(Merchant.status == "active").order_by(Merchant.id)))


def normalize(db: Session, user: User, body) -> dict:
    return {"card_id": body.card_id, "merchant_id": body.merchant_id, "amount_cents": parse_amount(body.amount),
            "order_ref": body.order_ref.strip(), "channel": body.channel}


def _user_accounts(user_id: str):
    return select(Account.id).where(Account.user_id == user_id)


def build_plan(db: Session, user: User, params: dict, now, lock: bool = False) -> Plan:
    card = cards.get_owned(db, user.id, params["card_id"], lock=lock)
    acc = acct.get_owned_account(db, user.id, card.account_id, lock=lock)
    merchant = db.get(Merchant, params["merchant_id"])
    if merchant is None:
        raise LantaiError("MERCHANT_NOT_FOUND", "商户不存在")
    amount = params["amount_cents"]

    if db.scalar(select(Transaction.id).where(
            Transaction.account_id.in_(_user_accounts(user.id)), Transaction.direction == "out",
            Transaction.counterparty_name == merchant.name, Transaction.memo == params["order_ref"])):
        raise LantaiError("ORDER_ALREADY_PAID", "该订单号已向此商户支付过", {"order_ref": params["order_ref"]})
    avail = acc.balance_cents
    if avail < amount:
        raise LantaiError("INSUFFICIENT_BALANCE", "余额不足")

    card_today = int(db.scalar(select(func.coalesce(func.sum(Transaction.amount_cents), 0)).where(
        Transaction.card_id == card.id, Transaction.direction == "out",
        Transaction.occurred_at >= clock.local_day_start_utc(now))))
    first_time = db.scalar(select(Transaction.id).where(
        Transaction.account_id.in_(_user_accounts(user.id)), Transaction.direction == "out",
        Transaction.counterparty_name == merchant.name)) is None
    change = {
        "card": {"status": card.status, "status_text": cards.STATUS_TEXT.get(card.status, card.status),
                 "online": card.online_enabled, "overseas": card.overseas_enabled,
                 "single": card.single_limit_cents, "daily": card.daily_limit_cents},
        "merchant": {"name": merchant.name, "status": merchant.status, "overseas": merchant.overseas},
        "channel": params["channel"], "card_today_cents": card_today, "first_time": first_time,
    }
    summary = {"action": "商户支付", "card": mask(card.card_no), "merchant": merchant.name,
               "amount": fmt(amount), "order_ref": params["order_ref"], "balance_after": fmt(acc.balance_cents - amount)}
    rctx = engine.build_context(db, user.id, acc, "merchant_payment", amount, now, change=change)
    return Plan("merchant_payment", params, summary, engine.evaluate(rctx),
                {"card": card, "account": acc, "merchant": merchant})


def execute(db: Session, op, plan: Plan, now) -> dict:
    card, acc, merchant = plan.data["card"], plan.data["account"], plan.data["merchant"]
    amount = plan.params["amount_cents"]
    acct.debit(db, acc, amount)
    txn = acct.add_txn(db, acc, "out", "other", amount, now, counterparty=merchant.name,
                       memo=plan.params["order_ref"], operation_id=op.id,
                       merchant_category=merchant.category, card_id=card.id)
    return {"transaction_id": txn.id, "order_ref": plan.params["order_ref"], "balance_after": fmt(acc.balance_cents),
            "executed_at": clock.iso(now)}
