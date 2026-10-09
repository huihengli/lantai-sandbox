"""Agent 通道 /api/v1：查询、prepare、取消、风险预检。"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import clock, config
from app.api.common import idem_key, intent_of, ok
from app.db import get_db
from app.errors import LantaiError
from app.models import (Account, DepositHolding, DepositProduct, Payee, Transaction)
from app.money import fmt, mask, parse_amount
from app.schemas import DepositIn, EarlyWithdrawIn, TransferIn
from app.security.auth import Principal, make_ctx, require
from app.services import account as acct
from app.services import audit, deposit, operation, transfer

router = APIRouter(prefix="/api/v1", tags=["agent"])

READ = Depends(require("read"))
PREPARE = Depends(require("prepare"))


def _account_view(a: Account) -> dict:
    return {"id": a.id, "type": a.type, "type_label": acct.TYPE_LABEL.get(a.type, a.type),
            "account_no_masked": mask(a.account_no), "currency": a.currency, "balance": fmt(a.balance_cents),
            "status": a.status}


def _owned(db: Session, p: Principal, account_id: str) -> Account:
    return acct.get_owned_account(db, p.user.id, account_id, require_active=False)


@router.get("/me")
def me(request: Request, p: Principal = READ):
    return ok(request, {"user_id": p.user.id, "name": p.user.name, "phone_masked": p.user.phone_masked,
                        "token_kind": p.kind, "scopes": sorted(p.scopes),
                        "token_expires_at": clock.iso(p.token.expires_at)})


@router.get("/accounts")
def accounts(request: Request, p: Principal = READ, db: Session = Depends(get_db)):
    rows = db.scalars(select(Account).where(Account.user_id == p.user.id).order_by(Account.id))
    return ok(request, [_account_view(a) for a in rows])


@router.get("/accounts/{account_id}/balance")
def balance(account_id: str, request: Request, p: Principal = READ, db: Session = Depends(get_db)):
    a = _owned(db, p, account_id)
    used = db.scalar(select(func.coalesce(func.sum(Transaction.amount_cents), 0)).where(
        Transaction.account_id == a.id, Transaction.direction == "out", Transaction.category == "transfer",
        Transaction.occurred_at >= clock.local_day_start_utc(clock.now())))
    return ok(request, {**_account_view(a), "available": fmt(a.balance_cents),
                        "single_limit": fmt(a.single_limit_cents), "daily_limit": fmt(a.daily_limit_cents),
                        "today_transferred_out": fmt(int(used)),
                        "daily_remaining": fmt(max(a.daily_limit_cents - int(used), 0))})


def _parse_dt(value: str | None, end_of_day: bool = False) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        raise LantaiError("VALIDATION_ERROR", f"时间格式不合法：{value}") from None
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    if len(value) <= 10 and end_of_day:  # 纯日期作为结束时间 → 当天末尾
        dt = dt.replace(hour=23, minute=59, second=59)
    return dt - config.TZ


@router.get("/accounts/{account_id}/transactions")
def transactions(account_id: str, request: Request, p: Principal = READ, db: Session = Depends(get_db),
                 from_: str | None = Query(None, alias="from"), to: str | None = None,
                 direction: str | None = Query(None, pattern="^(in|out)$"), category: str | None = None,
                 min_amount: str | None = None, limit: int = Query(20, ge=1, le=100), cursor: int = Query(0, ge=0)):
    a = _owned(db, p, account_id)
    stmt = select(Transaction).where(Transaction.account_id == a.id)
    if (start := _parse_dt(from_)):
        stmt = stmt.where(Transaction.occurred_at >= start)
    if (end := _parse_dt(to, end_of_day=True)):
        stmt = stmt.where(Transaction.occurred_at <= end)
    if direction:
        stmt = stmt.where(Transaction.direction == direction)
    if category:
        stmt = stmt.where(Transaction.category == category)
    if min_amount:
        stmt = stmt.where(Transaction.amount_cents >= parse_amount(min_amount))
    rows = db.scalars(stmt.order_by(Transaction.occurred_at.desc(), Transaction.id.desc())
                      .offset(cursor).limit(limit + 1)).all()
    items = [{"id": t.id, "direction": t.direction, "category": t.category, "amount": fmt(t.amount_cents),
              "fee": fmt(t.fee_cents), "balance_after": fmt(t.balance_after_cents),
              "counterparty": t.counterparty_name, "counterparty_account": t.counterparty_account_masked,
              "memo": t.memo, "occurred_at": clock.iso(t.occurred_at)} for t in rows[:limit]]
    return ok(request, {"items": items, "next_cursor": cursor + limit if len(rows) > limit else None})


@router.get("/payees")
def payees(request: Request, p: Principal = READ, db: Session = Depends(get_db)):
    rows = db.scalars(select(Payee).where(Payee.user_id == p.user.id, Payee.status == "active"))
    return ok(request, [{"id": r.id, "name": r.name, "account_no_masked": mask(r.account_no),
                         "bank": r.bank_name, "bank_code": r.bank_code,
                         "ever_paid": r.first_paid_at is not None,
                         "first_paid_at": clock.iso(r.first_paid_at)} for r in rows])


@router.get("/deposit/products")
def products(request: Request, p: Principal = READ, db: Session = Depends(get_db)):
    rows = db.scalars(select(DepositProduct).where(DepositProduct.status == "on_sale")
                      .order_by(DepositProduct.term_months))
    return ok(request, [deposit.product_view(r) for r in rows])


@router.get("/deposit/holdings")
def holdings(request: Request, p: Principal = READ, db: Session = Depends(get_db)):
    rows = db.scalars(select(DepositHolding).where(DepositHolding.user_id == p.user.id)
                      .order_by(DepositHolding.start_date.desc()))
    now = clock.now()
    return ok(request, [deposit.holding_view(h, now) for h in rows])


def _prepare(request: Request, db: Session, p: Principal, op_type: str, body):
    ctx = make_ctx(request, db, p, intent_of(body))
    out = audit.guarded(ctx, f"prepare:{op_type}",
                        lambda: operation.prepare(ctx, p.user, op_type, body, idem_key(request, body)))
    return ok(request, out)


@router.post("/transfers/prepare")
def transfer_prepare(body: TransferIn, request: Request, p: Principal = PREPARE, db: Session = Depends(get_db)):
    return _prepare(request, db, p, "transfer", body)


@router.post("/deposits/prepare")
def deposit_prepare(body: DepositIn, request: Request, p: Principal = PREPARE, db: Session = Depends(get_db)):
    return _prepare(request, db, p, "deposit_create", body)


@router.post("/deposits/{holding_id}/early-withdraw/prepare")
def early_withdraw_prepare(holding_id: str, request: Request, body: EarlyWithdrawIn | None = None,
                           p: Principal = PREPARE, db: Session = Depends(get_db)):
    body = body or EarlyWithdrawIn()
    body.holding_id = holding_id
    return _prepare(request, db, p, "deposit_early_withdraw", body)


@router.get("/operations/{op_id}")
def get_operation(op_id: str, request: Request, p: Principal = READ, db: Session = Depends(get_db)):
    return ok(request, operation.view(operation.get_op(db, p.user.id, op_id)))


@router.post("/operations/{op_id}/cancel")
def cancel_operation(op_id: str, request: Request, p: Principal = PREPARE, db: Session = Depends(get_db)):
    ctx = make_ctx(request, db, p)
    return ok(request, audit.guarded(ctx, "cancel", lambda: operation.cancel(ctx, p.user, op_id, "cancel"),
                                     op_id))


@router.post("/risk/precheck")
def precheck(body: TransferIn, request: Request, p: Principal = READ, db: Session = Depends(get_db)):
    """只评估转账风险，不创建操作。"""
    ctx = make_ctx(request, db, p, intent_of(body))

    def run():
        params = transfer.normalize(db, p.user, body)
        plan = transfer.build_plan(db, p.user, params, clock.now())
        audit.log(ctx, "risk_precheck", risk=plan.risk, detail={"summary": plan.summary})
        return {"summary": plan.summary, "risk": plan.risk}

    return ok(request, audit.guarded(ctx, "risk_precheck", run))
