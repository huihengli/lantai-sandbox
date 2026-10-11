"""Agent 通道 /api/v1：查询、prepare、取消、风险预检。"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app import clock, config
from app.api.common import idem_key, intent_of, ok
from app.db import get_db
from app.errors import LantaiError
from app.models import (Account, DepositHolding, DepositProduct, Payee, Transaction)
from app.money import fmt, mask, parse_amount
from app.schemas import (AccountLimitsIn, CardApplyIn, CardControlsIn, CardLimitsIn, CardOnlyIn, DepositIn,
                         EarlyWithdrawIn, HoldIn, HoldReleaseIn, MandateCancelIn, MerchantPayIn, PayeeIn, PayeePatch,
                         TransferIn)
from app.security.auth import Principal, make_ctx, require
from app.services import account as acct
from app.services import audit, cards as card_svc, deposit, holds as hold_svc, mandates as mandate_svc, operation, payments, transfer
from app.services import payees as payee_svc

router = APIRouter(prefix="/api/v1", tags=["agent"])

READ = Depends(require("read"))
PREPARE = Depends(require("prepare"))
PROTECT = Depends(require("protect"))  # 收紧类（保护性）直接操作


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
    held = acct.held_amount(db, a.id)
    return ok(request, {**_account_view(a), "held": fmt(held), "available": fmt(a.balance_cents - held),
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
                 min_amount: str | None = None, keyword: str | None = Query(None, max_length=50),
                 counterparty: str | None = Query(None, max_length=50),
                 merchant_category: str | None = Query(None, max_length=20),
                 limit: int = Query(20, ge=1, le=100), cursor: int = Query(0, ge=0)):
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
    if keyword:  # 备注或对方名称包含关键词
        like = f"%{keyword}%"
        stmt = stmt.where(or_(Transaction.memo.ilike(like), Transaction.counterparty_name.ilike(like)))
    if counterparty:
        stmt = stmt.where(Transaction.counterparty_name.ilike(f"%{counterparty}%"))
    if merchant_category:
        stmt = stmt.where(Transaction.merchant_category == merchant_category)
    rows = db.scalars(stmt.order_by(Transaction.occurred_at.desc(), Transaction.id.desc())
                      .offset(cursor).limit(limit + 1)).all()
    items = [{"id": t.id, "direction": t.direction, "category": t.category, "amount": fmt(t.amount_cents),
              "fee": fmt(t.fee_cents), "balance_after": fmt(t.balance_after_cents),
              "counterparty": t.counterparty_name, "counterparty_account": t.counterparty_account_masked,
              "merchant_category": t.merchant_category, "memo": t.memo, "occurred_at": clock.iso(t.occurred_at)} for t in rows[:limit]]
    return ok(request, {"items": items, "next_cursor": cursor + limit if len(rows) > limit else None})


@router.get("/payees")
def payees_list(request: Request, q: str | None = Query(None, max_length=30), p: Principal = READ,
                db: Session = Depends(get_db)):
    return ok(request, [payee_svc.view(r) for r in payee_svc.list_payees(db, p.user.id, q)])


@router.get("/payees/resolve")
def payees_resolve(request: Request, phone: str = Query(..., pattern=r"^\d{11}$"), p: Principal = READ,
                   db: Session = Depends(get_db)):
    """按手机号查询行内收款人（仅返回脱敏户名，限频）。"""
    ctx = make_ctx(request, db, p)
    return ok(request, audit.guarded(ctx, "payee_resolve", lambda: payee_svc.resolve_phone(db, p.user, phone)))


@router.post("/payees")
def payees_add(body: PayeeIn, request: Request, p: Principal = PREPARE, db: Session = Depends(get_db)):
    ctx = make_ctx(request, db, p)
    return ok(request, audit.guarded(ctx, "payee_add", lambda: payee_svc.add(ctx, p.user, body)))


@router.patch("/payees/{payee_id}")
def payees_update(payee_id: str, body: PayeePatch, request: Request, p: Principal = PREPARE,
                  db: Session = Depends(get_db)):
    ctx = make_ctx(request, db, p)
    return ok(request, audit.guarded(ctx, "payee_update",
                                     lambda: payee_svc.update_alias(ctx, p.user, payee_id, body.alias)))


@router.delete("/payees/{payee_id}")
def payees_remove(payee_id: str, request: Request, p: Principal = PREPARE, db: Session = Depends(get_db)):
    ctx = make_ctx(request, db, p)
    return ok(request, audit.guarded(ctx, "payee_remove", lambda: payee_svc.remove(ctx, p.user, payee_id)))


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


# ---------------- 卡片与额度 ----------------
@router.get("/cards")
def cards_list(request: Request, p: Principal = READ, db: Session = Depends(get_db)):
    return ok(request, [card_svc.view(c) for c in card_svc.list_cards(db, p.user.id)])


@router.get("/cards/{card_id}")
def cards_get(card_id: str, request: Request, p: Principal = READ, db: Session = Depends(get_db)):
    return ok(request, card_svc.view(card_svc.get_owned(db, p.user.id, card_id)))


def _direct(request: Request, db: Session, p: Principal, action: str, fn):
    ctx = make_ctx(request, db, p)
    return ok(request, audit.guarded(ctx, action, lambda: fn(ctx)))


@router.post("/cards/{card_id}/freeze")
def cards_freeze(card_id: str, request: Request, p: Principal = PROTECT, db: Session = Depends(get_db)):
    """冻结卡片（保护性，立即生效）。"""
    return _direct(request, db, p, "card_freeze", lambda ctx: card_svc.freeze(ctx, p.user, card_id))


@router.post("/cards/{card_id}/report-loss")
def cards_report_loss(card_id: str, request: Request, p: Principal = PROTECT, db: Session = Depends(get_db)):
    """挂失卡片（保护性，立即生效，不可撤销；补发走 reissue/prepare）。"""
    return _direct(request, db, p, "card_report_loss", lambda ctx: card_svc.report_loss(ctx, p.user, card_id))


@router.put("/cards/{card_id}/controls")
def cards_controls_tighten(card_id: str, body: CardControlsIn, request: Request, p: Principal = PROTECT,
                           db: Session = Depends(get_db)):
    """关闭交易开关（立即生效）。打开开关会返回 CONFIRM_REQUIRED，需走 controls/prepare。"""
    changes = {k: getattr(body, k) for k in card_svc.CONTROLS if getattr(body, k) is not None}
    return _direct(request, db, p, "card_controls_tighten", lambda ctx: card_svc.tighten_controls(ctx, p.user, card_id, changes))


@router.put("/cards/{card_id}/limits")
def cards_limits_lower(card_id: str, body: CardLimitsIn, request: Request, p: Principal = PROTECT,
                       db: Session = Depends(get_db)):
    """调低卡片额度（立即生效）。调高会返回 CONFIRM_REQUIRED，需走 limits/prepare。"""
    return _direct(request, db, p, "card_limits_lower",
                   lambda ctx: card_svc.lower_limits(ctx, p.user, card_id, *card_svc.parse_limits(body)))


@router.put("/accounts/{account_id}/limits")
def account_limits_lower(account_id: str, body: AccountLimitsIn, request: Request, p: Principal = PROTECT,
                         db: Session = Depends(get_db)):
    """调低账户转账额度（立即生效）。调高需走 limits/prepare。"""
    return _direct(request, db, p, "account_limits_lower",
                   lambda ctx: card_svc.lower_account_limits(ctx, p.user, account_id, *card_svc.parse_limits(body)))


@router.post("/cards/apply/prepare")
def cards_apply_prepare(body: CardApplyIn, request: Request, p: Principal = PREPARE, db: Session = Depends(get_db)):
    return _prepare(request, db, p, "card_apply", body)


@router.post("/cards/{card_id}/unfreeze/prepare")
def cards_unfreeze_prepare(card_id: str, request: Request, body: CardOnlyIn | None = None, p: Principal = PREPARE,
                           db: Session = Depends(get_db)):
    body = body or CardOnlyIn()
    body.card_id = card_id
    return _prepare(request, db, p, "card_unfreeze", body)


@router.post("/cards/{card_id}/reissue/prepare")
def cards_reissue_prepare(card_id: str, request: Request, body: CardOnlyIn | None = None, p: Principal = PREPARE,
                          db: Session = Depends(get_db)):
    body = body or CardOnlyIn()
    body.card_id = card_id
    return _prepare(request, db, p, "card_reissue", body)


@router.post("/cards/{card_id}/controls/prepare")
def cards_controls_prepare(card_id: str, body: CardControlsIn, request: Request, p: Principal = PREPARE,
                           db: Session = Depends(get_db)):
    body.card_id = card_id
    return _prepare(request, db, p, "card_controls", body)


@router.post("/cards/{card_id}/limits/prepare")
def cards_limits_prepare(card_id: str, body: CardLimitsIn, request: Request, p: Principal = PREPARE,
                         db: Session = Depends(get_db)):
    body.card_id = card_id
    return _prepare(request, db, p, "card_limits", body)


@router.post("/accounts/{account_id}/limits/prepare")
def account_limits_prepare(account_id: str, body: AccountLimitsIn, request: Request, p: Principal = PREPARE,
                           db: Session = Depends(get_db)):
    body.account_id = account_id
    return _prepare(request, db, p, "account_limits", body)


# ---------------- 代扣协议 ----------------
@router.get("/mandates")
def mandates_list(request: Request, status: str | None = Query(None, pattern="^(active|cancelled)$"),
                  p: Principal = READ, db: Session = Depends(get_db)):
    """已授权的代扣协议（商户、金额、周期、下次扣款日）。订阅识别与续费提醒由 Agent 基于它与流水完成。"""
    return ok(request, [mandate_svc.view(m) for m in mandate_svc.list_mandates(db, p.user.id, status)])


@router.post("/mandates/{mandate_id}/cancel/prepare")
def mandates_cancel_prepare(mandate_id: str, request: Request, body: MandateCancelIn | None = None,
                            p: Principal = PREPARE, db: Session = Depends(get_db)):
    body = body or MandateCancelIn()
    body.mandate_id = mandate_id
    return _prepare(request, db, p, "mandate_cancel", body)


# ---------------- 资金预留 ----------------
@router.get("/accounts/{account_id}/holds")
def holds_list(account_id: str, request: Request, status: str | None = Query(None, pattern="^(active|released|expired)$"),
               p: Principal = READ, db: Session = Depends(get_db)):
    a = _owned(db, p, account_id)
    out = [hold_svc.view(h) for h in hold_svc.list_holds(db, a.id, status)]
    db.commit()  # list_holds 会把到期预留惰性转为 expired
    return ok(request, out)


@router.post("/accounts/{account_id}/holds")
def holds_create(account_id: str, body: HoldIn, request: Request, p: Principal = PROTECT,
                 db: Session = Depends(get_db)):
    """预留（锁定）一笔资金：收紧类操作，直接生效。释放需 holds/{id}/release/prepare 并由用户确认。"""
    return _direct(request, db, p, "hold_create", lambda ctx: hold_svc.create(ctx, p.user, account_id, body))


@router.post("/holds/{hold_id}/release/prepare")
def holds_release_prepare(hold_id: str, request: Request, body: HoldReleaseIn | None = None,
                          p: Principal = PREPARE, db: Session = Depends(get_db)):
    body = body or HoldReleaseIn()
    body.hold_id = hold_id
    return _prepare(request, db, p, "hold_release", body)


# ---------------- 商户支付 ----------------
@router.get("/merchants")
def merchants_list(request: Request, p: Principal = READ, db: Session = Depends(get_db)):
    """商户目录（演示：鲜花、蛋糕、会员、超市、境外礼品）。"""
    return ok(request, [payments.merchant_view(m) for m in payments.list_merchants(db)])


@router.post("/payments/merchant/prepare")
def merchant_pay_prepare(body: MerchantPayIn, request: Request, p: Principal = PREPARE, db: Session = Depends(get_db)):
    """用借记卡向商户付款：受卡片状态/开关/额度、商户风险与可用余额约束，需用户确认。"""
    return _prepare(request, db, p, "merchant_payment", body)
