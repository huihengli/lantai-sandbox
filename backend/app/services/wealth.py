"""理财（净值型）：产品目录、持仓、申购、赎回，以及适当性校验。
推荐与对比由 Agent 做；银行只提供权威产品数据、客户风险等级与硬规则。
净值以 1e-4 元为单位（nav_bp），份额以 0.01 份为单位（shares_c）。"""
import re
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import clock
from app.errors import LantaiError
from app.models import Account, User, WealthHolding, WealthProduct
from app.money import fmt, mask, new_id, parse_amount, round_cents
from app.risk import engine
from app.services import account as acct
from app.services import risk_profile
from app.services.plan import Plan

KIND_TEXT = {"money": "货币基金", "bond": "债券基金", "mixed": "混合基金", "equity": "股票基金"}
_SHARES_RE = re.compile(r"^\d{1,10}(\.\d{1,2})?$")


def nav_text(nav_bp: int) -> str:
    return f"{nav_bp / 10000:.4f}"


def shares_text(shares_c: int) -> str:
    return f"{shares_c / 100:.2f}"


def suitability(user: User, now, product_risk: int) -> str:
    level, status = risk_profile.current(user, now)
    if level is None:
        return "unassessed"
    gap = product_risk - level
    return "match" if gap <= 0 else "mismatch" if gap == 1 else "forbidden"


def product_view(p: WealthProduct, user: User, now) -> dict:
    return {"id": p.id, "name": p.name, "kind": p.kind, "kind_text": KIND_TEXT.get(p.kind, p.kind),
            "risk_level": p.risk_level, "risk_label": f"R{p.risk_level}", "nav": nav_text(p.nav_bp),
            "nav_updated_at": clock.iso(p.nav_updated_at), "min_amount": fmt(p.min_amount_cents),
            "redeem_days": p.redeem_days, "description": p.description,
            "suitability": suitability(user, now, p.risk_level)}


def list_products(db: Session) -> list[WealthProduct]:
    return list(db.scalars(select(WealthProduct).where(WealthProduct.status == "on_sale")
                           .order_by(WealthProduct.risk_level, WealthProduct.id)))


def market_value(h: WealthHolding, p: WealthProduct) -> int:
    return round_cents(Decimal(h.shares_c) * p.nav_bp / 10000)


def holding_view(h: WealthHolding) -> dict:
    p = h.product
    value = market_value(h, p)
    pnl = value - h.cost_cents
    return {"id": h.id, "product_id": p.id, "product": p.name, "risk_label": f"R{p.risk_level}",
            "shares": shares_text(h.shares_c), "nav": nav_text(p.nav_bp), "market_value": fmt(value),
            "cost": fmt(h.cost_cents), "pnl": fmt(pnl),
            "pnl_pct": f"{(Decimal(pnl) / Decimal(h.cost_cents) * 100):.2f}%" if h.cost_cents else "0.00%",
            "account_id": h.account_id, "status": h.status}


def list_holdings(db: Session, user_id: str) -> list[WealthHolding]:
    return list(db.scalars(select(WealthHolding).where(WealthHolding.user_id == user_id)
                           .order_by(WealthHolding.status, WealthHolding.created_at.desc())))


# ---------------- 申购 ----------------
def normalize_subscribe(db: Session, user: User, body) -> dict:
    return {"account_id": body.account_id, "product_id": body.product_id, "amount_cents": parse_amount(body.amount)}


def build_subscribe_plan(db: Session, user: User, params: dict, now, lock: bool = False) -> Plan:
    acc = acct.get_owned_account(db, user.id, params["account_id"], lock=lock)
    prod = db.get(WealthProduct, params["product_id"])
    if prod is None or prod.status != "on_sale":
        raise LantaiError("PRODUCT_NOT_AVAILABLE", "产品不存在或已下架")
    amount = params["amount_cents"]
    shares_c = amount * 10000 // prod.nav_bp
    if amount < prod.min_amount_cents or shares_c <= 0:
        raise LantaiError("AMOUNT_BELOW_MIN", f"低于起购额 {fmt(prod.min_amount_cents)} 元")
    avail = acct.available_cents(db, acc)
    if avail < amount:
        raise LantaiError("INSUFFICIENT_BALANCE", "可用余额不足" if avail < acc.balance_cents else "余额不足",
                          {"balance": fmt(acc.balance_cents), "available": fmt(avail)})
    level, status = risk_profile.current(user, now)
    change = {"product": {"name": prod.name, "risk_level": prod.risk_level}, "user_level": level,
              "level_status": status, "user_label": risk_profile.LABELS.get(user.risk_level)}
    summary = {"action": "申购理财", "from": f"{acct.TYPE_LABEL.get(acc.type, acc.type)} {mask(acc.account_no)}",
               "product": prod.name, "risk_level": f"R{prod.risk_level}", "nav": nav_text(prod.nav_bp),
               "amount": fmt(amount), "shares": shares_text(shares_c) + " 份", "balance_after": fmt(acc.balance_cents - amount)}
    rctx = engine.build_context(db, user.id, acc, "wealth_subscribe", amount, now, change=change)
    return Plan("wealth_subscribe", params, summary, engine.evaluate(rctx),
                {"account": acc, "product": prod, "shares_c": shares_c})


def execute_subscribe(db: Session, op, plan: Plan, now) -> dict:
    acc, prod, shares_c = plan.data["account"], plan.data["product"], plan.data["shares_c"]
    amount = plan.params["amount_cents"]
    acct.debit(db, acc, amount)
    txn = acct.add_txn(db, acc, "out", "wealth_out", amount, now, counterparty=prod.name,
                       memo="理财申购", operation_id=op.id, merchant_category="理财")
    h = db.scalar(select(WealthHolding).where(WealthHolding.user_id == acc.user_id, WealthHolding.product_id == prod.id,
                                              WealthHolding.status == "active"))
    if h is None:
        h = WealthHolding(id=new_id("whd"), user_id=acc.user_id, product_id=prod.id, account_id=acc.id,
                          shares_c=0, cost_cents=0, status="active", created_at=now)
        db.add(h)
    h.shares_c += shares_c
    h.cost_cents += amount
    h.account_id = acc.id
    return {"holding_id": h.id, "transaction_id": txn.id, "shares": shares_text(shares_c), "nav": nav_text(prod.nav_bp),
            "balance_after": fmt(acc.balance_cents), "executed_at": clock.iso(now)}


# ---------------- 赎回 ----------------
def parse_shares(value: str | None) -> int | None:
    if value is None:
        return None
    if not _SHARES_RE.match(value) or Decimal(value) <= 0:
        raise LantaiError("AMOUNT_INVALID", "份额格式不合法：需为字符串，最多两位小数且大于 0")
    return int(Decimal(value) * 100)


def normalize_redeem(db: Session, user: User, body) -> dict:
    return {"holding_id": body.holding_id, "shares_c": parse_shares(body.shares), "account_id": body.account_id}


def build_redeem_plan(db: Session, user: User, params: dict, now, lock: bool = False) -> Plan:
    stmt = select(WealthHolding).where(WealthHolding.id == params["holding_id"])
    h = db.scalar(stmt.with_for_update() if lock else stmt)
    if h is None or h.user_id != user.id:
        raise LantaiError("RESOURCE_NOT_OWNED", "理财持仓不存在")
    if h.status != "active" or h.shares_c <= 0:
        raise LantaiError("HOLDING_NOT_ACTIVE", "该持仓已全部赎回")
    acc = acct.get_owned_account(db, user.id, params["account_id"] or h.account_id, lock=lock)
    sell = params["shares_c"] or h.shares_c
    if sell > h.shares_c:
        raise LantaiError("AMOUNT_ABOVE_MAX", f"超过可赎回份额 {shares_text(h.shares_c)}")
    prod = h.product
    value = round_cents(Decimal(sell) * prod.nav_bp / 10000)
    if value <= 0:
        raise LantaiError("AMOUNT_INVALID", "赎回金额过小")
    cost_part = h.cost_cents if sell == h.shares_c else round_cents(Decimal(h.cost_cents) * sell / h.shares_c)
    pnl = value - cost_part
    summary = {"action": "赎回理财", "to": f"{acct.TYPE_LABEL.get(acc.type, acc.type)} {mask(acc.account_no)}",
               "product": prod.name, "nav": nav_text(prod.nav_bp), "shares": shares_text(sell) + " 份",
               "amount": fmt(value), "pnl": fmt(pnl), "balance_after": fmt(acc.balance_cents + value)}
    rctx = engine.build_context(db, user.id, acc, "wealth_redeem", value, now, change={"pnl": fmt(-pnl) if pnl < 0 else None})
    return Plan("wealth_redeem", params, summary, engine.evaluate(rctx),
                {"account": acc, "holding": h, "sell": sell, "value": value, "cost_part": cost_part})


def execute_redeem(db: Session, op, plan: Plan, now) -> dict:
    acc, h = plan.data["account"], plan.data["holding"]
    sell, value, cost_part = plan.data["sell"], plan.data["value"], plan.data["cost_part"]
    acct.credit(db, acc, value)
    txn = acct.add_txn(db, acc, "in", "wealth_in", value, now, counterparty=h.product.name, memo="理财赎回",
                       operation_id=op.id, merchant_category="理财")
    h.shares_c -= sell
    h.cost_cents -= cost_part
    if h.shares_c == 0:
        h.status, h.closed_at = "closed", now
    return {"holding_id": h.id, "transaction_id": txn.id, "amount": fmt(value), "pnl": fmt(value - cost_part),
            "balance_after": fmt(acc.balance_cents), "executed_at": clock.iso(now)}
