"""定期：存入、持有、提前支取。"""
import calendar
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import clock
from app.errors import LantaiError
from app.models import DepositHolding, DepositProduct, User
from app.money import fmt, mask, new_id, parse_amount, round_cents
from app.risk import engine
from app.services import account as acct
from app.services.plan import Plan


def add_months(d: date, months: int) -> date:
    idx = d.month - 1 + months
    year, month = d.year + idx // 12, idx % 12 + 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def maturity_interest(principal: int, product: DepositProduct) -> int:
    return round_cents(Decimal(principal) * product.annual_rate_bp / 10000 * product.term_months / 12)


def early_interest(principal: int, product: DepositProduct, start: date, today: date) -> int:
    days = max((today - start).days, 0)
    return round_cents(Decimal(principal) * product.early_rate_bp / 10000 * days / 365)


def product_view(p: DepositProduct) -> dict:
    return {"id": p.id, "name": p.name, "term_months": p.term_months,
            "annual_rate": f"{p.annual_rate_bp / 100:.2f}%", "min_amount": fmt(p.min_amount_cents),
            "max_amount": fmt(p.max_amount_cents) if p.max_amount_cents else None,
            "early_withdraw_rate": f"{p.early_rate_bp / 100:.2f}%", "status": p.status}


def holding_view(h: DepositHolding, now) -> dict:
    full = maturity_interest(h.principal_cents, h.product)
    view = {"id": h.id, "product": h.product.name, "account_id": h.account_id,
            "principal": fmt(h.principal_cents), "start_date": h.start_date.isoformat(),
            "maturity_date": h.maturity_date.isoformat(), "status": h.status,
            "expected_interest_at_maturity": fmt(full)}
    if h.status == "holding":
        early = early_interest(h.principal_cents, h.product, h.start_date, clock.local(now).date())
        view.update(early_withdraw_interest_now=fmt(early), early_withdraw_loss=fmt(full - early))
    else:
        view["interest_paid"] = fmt(h.interest_paid_cents or 0)
    return view


# ---- 存入 ----
def normalize_create(db: Session, user: User, body) -> dict:
    return {"account_id": body.account_id, "product_id": body.product_id,
            "amount_cents": parse_amount(body.amount)}


def build_create_plan(db: Session, user: User, params: dict, now, lock: bool = False) -> Plan:
    acc = acct.get_owned_account(db, user.id, params["account_id"], lock=lock)
    prod = db.get(DepositProduct, params["product_id"])
    if prod is None or prod.status != "on_sale":
        raise LantaiError("PRODUCT_NOT_AVAILABLE", "产品不存在或已下架")
    amount = params["amount_cents"]
    if amount < prod.min_amount_cents:
        raise LantaiError("AMOUNT_BELOW_MIN", f"低于起存额 {fmt(prod.min_amount_cents)} 元")
    if prod.max_amount_cents and amount > prod.max_amount_cents:
        raise LantaiError("AMOUNT_ABOVE_MAX", f"高于限额 {fmt(prod.max_amount_cents)} 元")
    if acc.balance_cents < amount:
        raise LantaiError("INSUFFICIENT_BALANCE", "余额不足", {"balance": fmt(acc.balance_cents)})
    start = clock.local(now).date()
    summary = {"from": f"{acct.TYPE_LABEL.get(acc.type, acc.type)} {mask(acc.account_no)}",
               "product": prod.name, "term_months": prod.term_months,
               "annual_rate": f"{prod.annual_rate_bp / 100:.2f}%", "amount": fmt(amount),
               "expected_interest": fmt(maturity_interest(amount, prod)),
               "maturity_date": add_months(start, prod.term_months).isoformat(),
               "balance_after": fmt(acc.balance_cents - amount)}
    rctx = engine.build_context(db, user.id, acc, "deposit_create", amount, now)
    return Plan("deposit_create", params, summary, engine.evaluate(rctx), {"account": acc, "product": prod})


def execute_create(db: Session, op, plan: Plan, now) -> dict:
    acc, prod, amount = plan.data["account"], plan.data["product"], plan.params["amount_cents"]
    acct.debit(db, acc, amount)
    txn = acct.add_txn(db, acc, "out", "deposit_out", amount, now, counterparty=prod.name, operation_id=op.id)
    start = clock.local(now).date()
    holding = DepositHolding(id=new_id("hld"), user_id=acc.user_id, account_id=acc.id, product_id=prod.id,
                             principal_cents=amount, start_date=start,
                             maturity_date=add_months(start, prod.term_months), status="holding")
    db.add(holding)
    return {"holding_id": holding.id, "transaction_id": txn.id, "balance_after": fmt(acc.balance_cents),
            "maturity_date": holding.maturity_date.isoformat(), "executed_at": clock.iso(now)}


# ---- 提前支取 ----
def normalize_early(db: Session, user: User, body) -> dict:
    return {"holding_id": body.holding_id}


def _owned_holding(db: Session, user_id: str, holding_id: str, lock: bool) -> DepositHolding:
    stmt = select(DepositHolding).where(DepositHolding.id == holding_id)
    h = db.scalar(stmt.with_for_update() if lock else stmt)
    if h is None or h.user_id != user_id:
        raise LantaiError("RESOURCE_NOT_OWNED", "定期持有不存在")
    if h.status != "holding":
        raise LantaiError("HOLDING_NOT_ACTIVE", "该定期已结束")
    return h


def build_early_plan(db: Session, user: User, params: dict, now, lock: bool = False) -> Plan:
    h = _owned_holding(db, user.id, params["holding_id"], lock)
    acc = acct.get_owned_account(db, user.id, h.account_id, lock=lock)
    full = maturity_interest(h.principal_cents, h.product)
    early = early_interest(h.principal_cents, h.product, h.start_date, clock.local(now).date())
    summary = {"to": f"{acct.TYPE_LABEL.get(acc.type, acc.type)} {mask(acc.account_no)}",
               "product": h.product.name, "principal": fmt(h.principal_cents),
               "interest": fmt(early), "interest_loss": fmt(full - early),
               "total_credit": fmt(h.principal_cents + early), "maturity_date": h.maturity_date.isoformat(),
               "balance_after": fmt(acc.balance_cents + h.principal_cents + early)}
    rctx = engine.build_context(db, user.id, acc, "deposit_early_withdraw", h.principal_cents, now,
                                early={"loss": full - early, "full": full, "early": early})
    return Plan("deposit_early_withdraw", params, summary, engine.evaluate(rctx),
                {"account": acc, "holding": h, "interest": early})


def execute_early(db: Session, op, plan: Plan, now) -> dict:
    acc, h, interest = plan.data["account"], plan.data["holding"], plan.data["interest"]
    acct.credit(db, acc, h.principal_cents)
    acct.add_txn(db, acc, "in", "deposit_in", h.principal_cents, now, counterparty=h.product.name,
                 memo="提前支取本金", operation_id=op.id)
    if interest > 0:
        acct.credit(db, acc, interest)
        acct.add_txn(db, acc, "in", "interest", interest, now, counterparty=h.product.name,
                     memo="提前支取利息", operation_id=op.id)
    h.status, h.closed_at, h.interest_paid_cents = "withdrawn_early", now, interest
    return {"holding_id": h.id, "principal": fmt(h.principal_cents), "interest": fmt(interest),
            "balance_after": fmt(acc.balance_cents), "executed_at": clock.iso(now)}
